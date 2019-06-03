"""
Vision systems calibration using a chessboard calibration object
"""

import cv2
import numpy as np
from epypes import compgraph
from .geometry import rvec_to_rmat

findcbc_flags = {
    'default': cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
    'at_or_fq': cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_FILTER_QUADS
}

def find_cbc(im, pattern_size_wh, searchwin_size=5, findcbc_flags=None):
    """
    Find chessboard corners in the given image using OpenCV
    """

    if findcbc_flags == None:
        res = cv2.findChessboardCorners(im, pattern_size_wh)
    else:
        res = cv2.findChessboardCorners(im, pattern_size_wh, flags=findcbc_flags)

    found, corners = res

    if found:
        term = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_COUNT, 30, 0.1)
        cv2.cornerSubPix(im, corners, (searchwin_size, searchwin_size), (-1, -1), term)

    return res


def cbc_opencv_to_numpy(success, cbc_res):
    """
    Transform the result of OpenCV's chessboard corners detection
    to a numpy array of size (n_corners x 2). If corners were not
    identified correctly, the function returns None
    """

    if success:
        return cbc_res.reshape(-1, 2)
    else:
        return None


def find_corners_in_one_image(im, pattern_size_wh, searchwin_size=5, findcbc_flags=None):

    found, corners = find_cbc(im, pattern_size_wh, searchwin_size, findcbc_flags)
    return cbc_opencv_to_numpy(found, corners)


def prepare_corners(images, pattern_size_wh, searchwin_size=5, findcbc_flags=None):
    """
    Find chessboard corners in the supplied images.

    Returns `corners_list`, a list containing NumPy arrays (n_corners x 2) for images with successful
    corners detection and None for the unsuccessful ones
    """

    corners_list = []

    for i, im in enumerate(images):

        res = find_corners_in_one_image(im, pattern_size_wh, searchwin_size, findcbc_flags)
        corners_list.append(res)

    return corners_list


def prepare_corners_stereo(images1, images2, pattern_size_wh, searchwin_size=5, findcbc_flags=None):

    corners1 = prepare_corners(images1, pattern_size_wh, searchwin_size, findcbc_flags)
    corners2 = prepare_corners(images2, pattern_size_wh, searchwin_size, findcbc_flags)

    res1 = []
    res2 = []
    for c1, c2 in zip(corners1, corners2):
        if not ((c1 is None) or (c2 is None)):
            res1.append(c1)
            res2.append(c2)

    num_images = len(res1)

    return res1, res2, num_images


def calibrate_camera(im_wh, object_points, image_points):
    """
    Perform camera calibration using a set of images with the chessboard pattern

    image_points -- a list of chessboard corners shaped as NumPy arrays (n_points x 2)

    Returns a tuple as a result of the cv2.calibrateCamera function call,
    containing the following calibration results:
    rms, camera_matrix, dist_coefs, rvecs, tvecs
    """

    res = cv2.calibrateCamera(object_points, image_points, im_wh, None, None)
    return res


def calibrate_stereo(object_points, impoints_1, impoints_2, cm_1, dc_1, cm_2, dc_2, im_wh):

    res = cv2.stereoCalibrate(object_points, impoints_1, impoints_2, cm_1, dc_1, cm_2, dc_2, im_wh)

    R, T, E, F = res[-4:]

    return R, T, E, F


def prepare_object_points(num_images, pattern_size_wh, square_size):
    """
    Prepare a list of object points matrices
    """

    pattern_points = get_pattern_points(pattern_size_wh, square_size)
    return make_list_of_identical_pattern_points(num_images, pattern_points)


def make_list_of_identical_pattern_points(num_images, pattern_points):
    return [pattern_points for i in range(num_images)]


def get_pattern_points(pattern_size_wh, square_size):
    """
    Form a matrix with object points for a chessboard calibration object
    """

    pattern_points = np.zeros((np.prod(pattern_size_wh), 3), np.float32)
    pattern_points[:, :2] = np.indices(pattern_size_wh).T.reshape(-1, 2)
    pattern_points *= square_size
    return pattern_points


def solve_pnp_ransac(pattern_points, image_points, cam_matrix, dist_coefs,
                     use_extrinsic_guess=False, iter_count=100, reproj_err_threshold=8.0, confidence=0.99):

    return cv2.solvePnPRansac(pattern_points, image_points, cam_matrix, dist_coefs,
                              use_extrinsic_guess, iter_count, reproj_err_threshold, confidence)


def project_points(object_points, rvec, tvec, cm, dc):
    """
    Project points using cv2.projectPoints
    and reshape the result to (n_points, 2)
    """

    projected, _ = cv2.projectPoints(object_points, rvec, tvec, cm, dc)
    return projected.reshape(-1, 2)


def reprojection_rms(impoints_known, impoints_reprojected):
    """
    Compute root mean square (RMS) error of points
    reprojection (cv2.projectPoints).

    Both input NumPy arrays should be of shape (n_points, 2)
    """

    diff = impoints_known - impoints_reprojected

    squared_distances = np.sum(np.square(diff), axis=1)
    rms = np.sqrt(np.mean(squared_distances))

    return rms


def get_im_wh(im):
    h, w = im.shape[:2]
    return w, h


def undistort_and_rectify_images_stereo(images1, images2, cm1, dc1, cm2, dc2, R1, R2, P1, P2):

    im_wh = get_im_wh(images1[0])

    maps1 = cv2.initUndistortRectifyMap(cm1, dc1, R1, P1, im_wh, m1type=cv2.CV_16SC2)
    maps2 = cv2.initUndistortRectifyMap(cm2, dc2, R2, P2, im_wh, m1type=cv2.CV_16SC2)

    interp_method = cv2.INTER_LINEAR

    images1_rect = [cv2.remap(im, maps1[0], maps1[1], interp_method) for im in images1]
    images2_rect = [cv2.remap(im, maps2[0], maps2[1], interp_method) for im in images2]

    return images1_rect, images2_rect, maps1, maps2


def prepare_indices_stereocalib(corners1, corners2):
    """
    Return indices between 0 and num_images
    for which chessboard corners were detected
    in both left and right image (i.e. neither in corners1 
    nor in corners2 there is None at those indices).
    """

    indices = []

    idx = 0
    for c1, c2 in zip(corners1, corners2):
        
        if not ((c1 is None) or (c2 is None)):
            indices.append(idx)
        
        idx += 1

    return indices


def create_stereo_cg():

    cg_base = CGCalibrateStereoBase()

    func_dict = {
        'prepare_corners': prepare_corners_stereo,
        'prepare_object_points': prepare_object_points,
    }

    func_io = {
        
        'prepare_corners': (
            ('calibration_images_1', 'calibration_images_2', 'pattern_size_wh'), 
            ('image_points_1', 'image_points_2', 'num_images')
        ),

        'prepare_object_points': (
            ('num_images', 'pattern_size_wh', 'square_size'), 
            'object_points'
        ),

    }

    cg_front = compgraph.CompGraph(func_dict, func_io)

    return compgraph.graph_union(cg_front, cg_base)


class CGCalibrateCamera(compgraph.CompGraph):

    def __init__(self):

        func_dict = {
            'prepare_corners': prepare_corners,
            'count_images': lambda lst: len(lst),
            'prepare_object_points': prepare_object_points,
            'calibrate_camera': calibrate_camera
        }

        func_io = {
            'prepare_corners': (('calibration_images', 'pattern_size_wh'), 'image_points'),
            'count_images': ('calibration_images', 'num_images'),
            'prepare_object_points': (('num_images', 'pattern_size_wh', 'square_size'), 'object_points'),
            'calibrate_camera': (('im_wh', 'object_points', 'image_points'),
                                 ('rms', 'camera_matrix', 'dist_coefs', 'rvecs', 'tvecs'))
        }

        super(CGCalibrateCamera, self).__init__(func_dict, func_io)


class CGSolvePnP(compgraph.CompGraph):

    def __init__(self):

        func_dict = {
            'detect_corners': find_corners_in_one_image,
            'solve_pnp': cv2.solvePnP,
            'rvec_to_rmat': rvec_to_rmat
        }

        func_io = {
            'detect_corners': (('image', 'pattern_size_wh'), 'image_points'),
            'solve_pnp': (('pattern_points', 'image_points', 'cam_matrix', 'dist_coefs'),
                          ('pnp_retval', 'rvec', 'tvec')),

            'rvec_to_rmat': ('rvec', 'rmat')
        }

        super(CGSolvePnP, self).__init__(func_dict, func_io)


class CGPreparePointsStereo(compgraph.CompGraph):

    def __init__(self):

        func_dict = {
            'prepare_corners_1': prepare_corners,
            'prepare_corners_2': prepare_corners,
            'prepare_indices': prepare_indices_stereocalib,
            'get_pattern_points': get_pattern_points,
        }

        func_io = {
            'prepare_corners_1': (('calibration_images_1', 'pattern_size_wh'), 'image_points_1'),
            'prepare_corners_2': (('calibration_images_2', 'pattern_size_wh'), 'image_points_2'),
            'prepare_indices': (('image_points_1', 'image_points_2'), 'indices'),
            'get_pattern_points': (('pattern_size_wh', 'square_size'), 'pattern_points'),
        }

        super(CGPreparePointsStereo, self).__init__(func_dict, func_io)


class CGCalibrateStereo(compgraph.CompGraph):

    def __init__(self):
        cg = create_stereo_cg()
        super(CGCalibrateStereo, self).__init__(cg.functions, cg.func_io)


class CGCalibrateStereoBase(compgraph.CompGraph):

    def __init__(self):

        func_dict = {
            'calibrate_camera_1': calibrate_camera,
            'calibrate_camera_2': calibrate_camera,
            'calibrate_stereo': calibrate_stereo,
            'compute_rectification_transforms': cv2.stereoRectify
        }

        func_io = {
            'calibrate_camera_1': (('im_wh', 'object_points', 'image_points_1'),
                                  ('rms_1', 'cm_1', 'dc_1', 'rvecs_1', 'tvecs_1')),
            'calibrate_camera_2': (('im_wh', 'object_points', 'image_points_2'),
                                   ('rms_2', 'cm_2', 'dc_2', 'rvecs_2', 'tvecs_2')),
            'calibrate_stereo' : (('object_points', 'image_points_1', 'image_points_2', 'cm_1', 'dc_1', 'cm_2', 'dc_2', 'im_wh'),
                                  ('stereo_rmat', 'stereo_tvec', 'essential_mat', 'fundamental_mat')),
            'compute_rectification_transforms': (('cm_1', 'dc_1', 'cm_2', 'dc_2', 'im_wh', 'stereo_rmat', 'stereo_tvec'),
                                                 ('R1', 'R2', 'P1', 'P2', 'Q', 'validPixROI1', 'validPixROI2'))
        }

        super(CGCalibrateStereoBase, self).__init__(func_dict, func_io)


class CGFindCorners(compgraph.CompGraph):

     def __init__(self):

         func_dict = {
            'find_corners': find_cbc,
            'reformat_corners': cbc_opencv_to_numpy
        }

         func_io = {
            'find_corners': (('image', 'pattern_size_wh'), ('success', 'corners_opencv')),
            'reformat_corners': (('success', 'corners_opencv'), 'corners_np')
        }

         super(CGFindCorners, self).__init__(func_dict, func_io)
