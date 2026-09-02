"""Domain exceptions for data quality checks.

Subclassing DRF's APIException lets the viewset stay thin: raising these from the logic layer maps
to the right HTTP status automatically, no per-action try/except needed.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class CheckNameConflict(APIException):
    """A 409 for a check name already taken within the project.

    ``detail`` must stay a plain string: the exceptions_hog handler cannot render dict details
    (it 500s).
    """

    status_code = status.HTTP_409_CONFLICT
    default_detail = "A check with this name already exists in this project."
    default_code = "check_name_conflict"
