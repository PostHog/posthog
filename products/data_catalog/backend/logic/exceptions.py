"""Domain exceptions for the metric lifecycle.

Subclassing DRF's APIException lets the viewset stay thin: raising these from the logic layer maps
to the right HTTP status automatically, no per-action try/except needed.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class MetricDrifted(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This metric's definition has drifted from its source insight. Refresh it from the insight "
        "or unlink the insight before approving."
    )
    default_code = "metric_drifted"


class SourceInsightUnavailable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "The source insight is no longer available. Edit the definition directly or unlink the insight."
    default_code = "source_insight_unavailable"


class MetricHasNoDefinition(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This metric has no definition to run. It is name and description only."
    default_code = "metric_has_no_definition"


class CatalogConflict(APIException):
    """A 409 for catalog conflicts (duplicate certification, ambiguous table name, existing proposal)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This catalog entry conflicts with an existing one."
    default_code = "catalog_conflict"
