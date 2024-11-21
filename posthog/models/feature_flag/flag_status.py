import structlog

from enum import StrEnum
from .feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

FeatureFlagStatusReason = str


class FeatureFlagStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    DELETED = "deleted"
    UNKNOWN = "unknown"


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
        # The amount of time considered "recent" for the purposes of determining staleness .
        stale_window: str = "-30d",
    ):
        self.feature_flag_id = feature_flag_id
        self.stale_window = stale_window

    def get_status(self) -> tuple[FeatureFlagStatus, FeatureFlagStatusReason]:
        try:
            flag = FeatureFlag.objects.get(pk=self.feature_flag_id)
        except FeatureFlag.DoesNotExist:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be found"

        if flag.deleted:
            return FeatureFlagStatus.DELETED, "Flag has been deleted"

        # See if the flag is set to 100% on one variant (or 100% on rolled out and active if boolean flag).
        is_flag_fully_enabled, fully_enabled_explanation = self.is_flag_fully_enabled(flag)
        if is_flag_fully_enabled:
            return FeatureFlagStatus.STALE, fully_enabled_explanation

        # Final, and most expensive check: see if the flag has been evaluated recently.
        if self.is_flag_unevaluated_recently(flag):
            return FeatureFlagStatus.STALE, "Flag has not been evaluated recently"

        return FeatureFlagStatus.ACTIVE, "Flag is not fully rolled out and may still be actively called"

    def is_flag_fully_enabled(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        # If flag is not active, it is not enabled. This flag may still be stale,
        # but only if isn't being evaluated, which will be determined later.
        if not flag.active:
            logger.debug(f"Flag {flag.id} is not active")
            return False, None

        # If flag is using super groups and any super group is rolled out to 100%,
        # it is fully enabled.
        if flag.filters.get("super_groups", None):
            for super_group in flag.filters.get("super_groups"):
                rollout_percentage = super_group.get("rollout_percentage")
                properties = super_group.get("properties", [])
                if rollout_percentage == 100 and len(properties) == 0:
                    logger.debug(f"Flag {flag.id} has super group is rolled out to 100%")
                    return True, "Super group is rolled out to 100%"

        # If flag is using holdout groups and any holdout group is rolled out to 100%,
        # it is fully enabled.
        if flag.filters.get("holdout_groups", None):
            for holdout_group in flag.filters.get("holdout_groups"):
                rollout_percentage = holdout_group.get("rollout_percentage")
                properties = holdout_group.get("properties", [])
                if rollout_percentage == 100 and len(properties) == 0:
                    logger.debug(f"Flag {flag.id} has holdout group is rolled out to 100%")
                    return True, "Holdout group is rolled out to 100%"

        multivariate = flag.filters.get("multivariate", None)
        if multivariate and self.is_multivariate_flag_fully_enabled(flag):
            return True, "One variant and one release condition are rolled out to 100%"
        elif self.is_boolean_flag_fully_enabled(flag):
            return True, "Boolean flag has a release condition rolled out to 100%"

        return False, None

    def is_multivariate_flag_fully_enabled(self, flag: FeatureFlag) -> bool:
        # If flag is multivariant and one variant is rolled out to 100%,
        # and there is a release condition set to 100%, it is fully enabled.
        #
        # Alternatively, if there is a release condition set to 100% and it has a
        # variant override, the flag is fully enabled.
        some_variant_fully_enabled = False
        some_release_condition_fully_enabled = False
        some_fully_enabled_release_condition_has_override = False

        multivariate = flag.filters.get("multivariate", None)
        variants = multivariate.get("variants", [])
        for variant in variants:
            if variant.get("rollout_percentage") == 100:
                some_variant_fully_enabled = True

        for release_condition in flag.filters.get("groups", []):
            rollout_percentage = release_condition.get("rollout_percentage")
            properties = release_condition.get("properties", [])
            if rollout_percentage == 100 and len(properties) == 0:
                some_release_condition_fully_enabled = True
                some_fully_enabled_release_condition_has_override = release_condition.get("variant", None) is not None

        return some_release_condition_fully_enabled and (
            some_fully_enabled_release_condition_has_override or some_variant_fully_enabled
        )

    def is_boolean_flag_fully_enabled(self, flag: FeatureFlag) -> bool:
        # An active flag with no release conditions is still considered fully enabled.
        # This isn't a supported state, but in place to support legacy data.
        if flag.filters is None or len(flag.filters) == 0:
            logger.debug(f"Boolean flag {flag.id} has no release conditions, so it is rolled out to 100%")
            return True

        # If flag is boolean flag and rolled release conditions have rolled out to 100%, it is fully enabled.
        # The fully enabled release condition must have no properties set.
        release_conditions = flag.filters.get("groups", [])
        for release_condition in release_conditions:
            rollout_percentage = release_condition.get("rollout_percentage")
            properties = release_condition.get("properties", [])
            if rollout_percentage == 100 and len(properties) == 0:
                logger.debug(f"Boolean flag {flag.id} has a release conditions rolled out to 100%")
                return True

        return False

    def is_flag_unevaluated_recently(self, flag: FeatureFlag) -> bool:
        recent_evaluations = self.get_recent_evaluations(flag)
        return len(recent_evaluations) == 0

    def get_recent_evaluations(self, flag: FeatureFlag) -> bool:
        from posthog.schema import EventsQuery, EventsQueryResponse
        from posthog.hogql_queries.events_query_runner import EventsQueryRunner

        eq = EventsQuery(
            after=self.stale_window,
            event="$feature_flag_called",
            properties=[
                {
                    "key": "$feature_flag",
                    "operator": "exact",
                    "type": "event",
                    "value": flag.key,
                }
            ],
            select=[
                "if(toString(properties.$feature_flag_response) IN ['1', 'true'], 'true', 'false') -- Feature Flag Response"
            ],
            # We only care if there has been one or more recent call, so ask ClickHouse for one result
            limit=1,
        )

        result: EventsQueryResponse = EventsQueryRunner(query=eq, team=flag.team).calculate()

        logger.debug(f"Flag {flag.id} has {len(result.results)} recent ({self.stale_window}) calls")
        return result.results
