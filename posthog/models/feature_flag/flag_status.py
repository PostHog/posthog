from datetime import UTC, datetime, timedelta
from enum import StrEnum

import structlog

from posthog.date_util import thirty_days_ago

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
# - ACTIVE: The feature flag is actively evaluated and in use.
# - STALE: The feature flag is likely safe to remove. Detection uses the best available signal:
#       1. If last_called_at exists: flag hasn't been called in 30+ days (usage-based)
#       2. If last_called_at is NULL: flag is 100% rolled out and 30+ days old (config-based)
# - DELETED: The feature flag has been soft deleted.
# - UNKNOWN: The feature flag is not found in the database.
#
# When we update the logic for stale flags, do check/update the function `_filter_request`` in feature_flag.py
class FeatureFlagStatusChecker:
    def __init__(
        self,
        feature_flag_id: int | None = None,
        feature_flag: FeatureFlag | None = None,
    ):
        self.feature_flag_id = feature_flag_id
        self.feature_flag = feature_flag

    def get_status(self) -> tuple[FeatureFlagStatus, FeatureFlagStatusReason]:
        if not self.feature_flag_id and not self.feature_flag:
            return FeatureFlagStatus.UNKNOWN, "Must provide feature flag or feature flag id"

        try:
            flag = FeatureFlag.objects.get(pk=self.feature_flag_id) if self.feature_flag_id else self.feature_flag
        except FeatureFlag.DoesNotExist:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be found"

        if not flag:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be loaded"

        if flag.deleted:
            return FeatureFlagStatus.DELETED, "Flag has been deleted"

        # Disabled flags are not evaluated for staleness
        if not flag.active:
            return FeatureFlagStatus.ACTIVE, "Flag is disabled (not evaluated for staleness)"

        # Use the best available signal to determine if flag is stale:
        # 1. If we have usage data (last_called_at), use that - it's the most accurate
        # 2. If no usage data, fall back to configuration-based detection

        if flag.last_called_at is not None:
            # We have usage data - use it as the primary signal
            is_stale, stale_reason = self.is_flag_stale_by_usage(flag)
            if is_stale:
                return FeatureFlagStatus.STALE, stale_reason
            # Flag has recent usage
            days_since_called = (datetime.now(UTC) - flag.last_called_at).days
            if days_since_called == 0:
                return FeatureFlagStatus.ACTIVE, "Flag was called today"
            return (
                FeatureFlagStatus.ACTIVE,
                f"Flag was last called {days_since_called} day{'s' if days_since_called != 1 else ''} ago",
            )
        else:
            # No usage data - fall back to configuration-based detection
            # Only for flags that are old enough (30+ days) to have had a chance to be called
            is_flag_at_least_thirty_days_old = flag.created_at < thirty_days_ago()
            if is_flag_at_least_thirty_days_old:
                is_fully_rolled_out, rolled_out_reason = self.is_flag_fully_rolled_out(flag)
                if is_fully_rolled_out:
                    return FeatureFlagStatus.STALE, rolled_out_reason

        return FeatureFlagStatus.ACTIVE, "Flag has no usage data yet"

    def is_flag_stale_by_usage(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        """
        Check if flag is stale based on usage data (last_called_at).
        A flag is stale if it hasn't been called in 30+ days.
        """
        assert flag.last_called_at is not None, "last_called_at must not be None"
        stale_threshold = datetime.now(UTC) - timedelta(days=30)

        if flag.last_called_at < stale_threshold:
            days_since_called = (datetime.now(UTC) - flag.last_called_at).days
            return True, f"Flag has not been called in {days_since_called} days"

        return False, ""

    def is_flag_fully_rolled_out(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        multivariate = flag.filters.get("multivariate", None)
        if multivariate:
            is_multivariate_flag_fully_rolled_out, fully_rolled_out_variant_name = (
                self.is_multivariate_flag_fully_rolled_out(flag)
            )
        if multivariate and is_multivariate_flag_fully_rolled_out:
            return True, f'This flag will always use the variant "{fully_rolled_out_variant_name}"'
        elif not multivariate and self.is_boolean_flag_fully_rolled_out(flag):
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
