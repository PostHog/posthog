import structlog
from django.db.models.query import QuerySet
from posthog.schema import (
    FeatureFlagStatus,
)

from .feature_flag import (
    FeatureFlag,
)

logger = structlog.get_logger(__name__)


# FeatureFlagStatusChecker is used to determine the status of a feature flag for a given user.
# Eventually, this may be used to automatically archive old flags that are no longer in use.
#
# Status can be one of the following:
# - ACTIVE: The feature flag is actively evaluated and the evaluations continue to vary.
# - STALE: The feature flag either has not been evaluated recently, or the evaluation has not changed recently.
# - DELETED: The feature flag has been soft deleted.
# - UNKNOWN: The feature flag is not found in the database.
class FeatureFlagStatusChecker:
    def __init__(
        self,
        feature_flag_id: str,
        # The amount of time considered "recent" for the purposes of determining staleness.
        stale_window: str = "-30d",
    ):
        self.feature_flag_id = feature_flag_id
        self.stale_window = stale_window

    def get_status(self) -> FeatureFlagStatus:
        flag: FeatureFlag = FeatureFlag.objects.get(pk=self.feature_flag_id)

        if flag is None:
            return FeatureFlagStatus.UNKNOWN
        if flag.deleted:
            return FeatureFlagStatus.DELETED

    def get_recent_evaluations(self) -> QuerySet:
        return
