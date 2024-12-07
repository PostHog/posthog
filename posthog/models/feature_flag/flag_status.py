import structlog

from enum import StrEnum
from .feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

FeatureFlagStatusReason = str


class FeatureFlagStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    STALE = "stale"
    DELETED = "deleted"
    UNKNOWN = "unknown"


# FeatureFlagStatusChecker is used to determine the status of a feature flag for a given user.
# Eventually, this may be used to automatically archive old flags that are no longer in use.
#
# Status can be one of the following:
# - ACTIVE: The feature flag is actively evaluated and the evaluations continue to vary.
# - STALE: The feature flag has been fully rolled out to users. Its evaluations can not vary.
# - INACTIVE: The feature flag is not being actively evaluated. STALE takes precedence over INACTIVE.
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

    def get_status(self) -> tuple[FeatureFlagStatus, FeatureFlagStatusReason]:
        try:
            flag = FeatureFlag.objects.get(pk=self.feature_flag_id)
        except FeatureFlag.DoesNotExist:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be found"

        if flag.deleted:
            return FeatureFlagStatus.DELETED, "Flag has been deleted"

        # See if the flag is set to 100% on one variant (or 100% on rolled out and active if boolean flag).
        is_flag_fully_rolled_out, fully_rolled_out_explanation = self.is_flag_fully_rolled_out(flag)
        if is_flag_fully_rolled_out:
            return FeatureFlagStatus.STALE, fully_rolled_out_explanation

        # Final, and most expensive check: see if the flag has been evaluated recently.
        if self.is_flag_unevaluated_recently(flag):
            return FeatureFlagStatus.INACTIVE, "Flag has not been evaluated recently"

        return FeatureFlagStatus.ACTIVE, "Flag is not fully rolled out and may still be active"

    def is_flag_fully_rolled_out(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        # If flag is not active, it is not fully rolled out. This flag may still be stale,
        # but only if isn't being evaluated, which will be determined later.
        if not flag.active:
            logger.debug(f"Flag {flag.id} is not active")
            return False, ""

        # If flag is using super groups and any super group is rolled out to 100%,
        # it is fully rolled out.
        if flag.filters.get("super_groups", None):
            for super_group in flag.filters.get("super_groups"):
                if self.is_group_fully_rolled_out(super_group):
                    logger.debug(f"Flag {flag.id} has super group is rolled out to 100%")
                    return True, "Super group is rolled out to 100%"

        # If flag is using holdout groups and any holdout group is rolled out to 100%,
        # it is fully rolled out.
        if flag.filters.get("holdout_groups", None):
            for holdout_group in flag.filters.get("holdout_groups"):
                if self.is_group_fully_rolled_out(holdout_group):
                    logger.debug(f"Flag {flag.id} has holdout group is rolled out to 100%")
                    return True, "Holdout group is rolled out to 100%"

        multivariate = flag.filters.get("multivariate", None)
        if multivariate:
            is_multivariate_flag_fully_rolled_out, fully_rolled_out_variant_name = (
                self.is_multivariate_flag_fully_rolled_out(flag)
            )
        if multivariate and is_multivariate_flag_fully_rolled_out:
            return True, f'This flag will always use the variant "{fully_rolled_out_variant_name}"'
        elif self.is_boolean_flag_fully_rolled_out(flag):
            return True, 'This boolean flag will always evaluate to "true"'

        return False, ""

    def is_multivariate_flag_fully_rolled_out(self, flag: FeatureFlag) -> tuple[bool, str]:
        # If flag is multivariant and one variant is rolled out to 100%,
        # and there is a release condition set to 100%, it is fully rolled out.
        #
        # Alternatively, if there is a release condition set to 100% and it has a
        # variant override, the flag is fully rolled out.
        fully_rolled_out_variant_key: str | None = None
        some_release_condition_fully_rolled_out = False
        fully_rolled_out_release_condition_variant_override: str | None = None

        multivariate = flag.filters.get("multivariate", None)
        variants = multivariate.get("variants", [])
        for variant in variants:
            if variant.get("rollout_percentage") == 100:
                fully_rolled_out_variant_key = variant.get("key")
                break

        for release_condition in flag.filters.get("groups", []):
            if self.is_group_fully_rolled_out(release_condition):
                some_release_condition_fully_rolled_out = True
                fully_rolled_out_release_condition_variant_override = (
                    fully_rolled_out_release_condition_variant_override or release_condition.get("variant", None)
                )

        fully_rolled_out_variant = (
            fully_rolled_out_release_condition_variant_override or fully_rolled_out_variant_key or ""
        )
        return some_release_condition_fully_rolled_out and (
            fully_rolled_out_release_condition_variant_override is not None or fully_rolled_out_variant_key is not None
        ), fully_rolled_out_variant

    def is_group_fully_rolled_out(self, group: dict) -> bool:
        rollout_percentage = group.get("rollout_percentage")
        properties = group.get("properties", [])
        return rollout_percentage == 100 and len(properties) == 0

    def is_boolean_flag_fully_rolled_out(self, flag: FeatureFlag) -> bool:
        # An active flag with no release conditions is still considered fully rolled out.
        # This isn't a supported state, but in place to support legacy data.
        if flag.filters is None or len(flag.filters) == 0:
            logger.debug(f"Boolean flag {flag.id} has no release conditions, so it is rolled out to 100%")
            return True

        # If flag is boolean flag and rolled release conditions have rolled out to 100%, it is fully rolled out.
        # The fully rolled out release condition must have no properties set.
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

    def get_recent_evaluations(self, flag: FeatureFlag) -> list[list[str]]:
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
            select=[],
            # We only care if there has been one or more recent call, so ask ClickHouse for one result
            limit=1,
        )

        result: EventsQueryResponse = EventsQueryRunner(query=eq, team=flag.team).calculate()

        logger.debug(f"Flag {flag.id} has {len(result.results)} recent ({self.stale_window}) calls")
        return result.results
