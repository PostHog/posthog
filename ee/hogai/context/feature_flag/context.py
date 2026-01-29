from posthog.models import Team
from posthog.models.feature_flag import FeatureFlag
from posthog.sync import database_sync_to_async

from .prompts import (
    FEATURE_FLAG_CONTEXT_TEMPLATE,
    FEATURE_FLAG_NOT_FOUND_TEMPLATE,
    FEATURE_FLAG_RELEASE_CONDITIONS_TEMPLATE,
    FEATURE_FLAG_ROLLOUT_PERCENTAGE_TEMPLATE,
    FEATURE_FLAG_VARIANTS_TEMPLATE,
)


class FeatureFlagContext:
    """
    Context class for feature flags used across the assistant.

    Provides methods to fetch feature flag data and format it for AI consumption.
    """

    def __init__(
        self,
        team: Team,
        flag_id: int | None = None,
        flag_key: str | None = None,
    ):
        self._team = team
        self._flag_id = flag_id
        self._flag_key = flag_key

    async def aget_feature_flag(self) -> FeatureFlag | None:
        """Fetch the feature flag from the database."""
        try:
            if self._flag_id is not None:
                return await FeatureFlag.objects.aget(id=self._flag_id, team=self._team, deleted=False)
            elif self._flag_key is not None:
                return await FeatureFlag.objects.aget(key=self._flag_key, team=self._team, deleted=False)
            return None
        except FeatureFlag.DoesNotExist:
            return None

    def get_not_found_message(self) -> str:
        """Return a formatted not found message."""
        identifier = f"id={self._flag_id}" if self._flag_id else f"key={self._flag_key}"
        return FEATURE_FLAG_NOT_FOUND_TEMPLATE.format(identifier=identifier)

    @database_sync_to_async
    def format_feature_flag(self, flag: FeatureFlag) -> str:
        """Format feature flag data for AI consumption."""
        rollout_percentage_section = ""
        if flag.rollout_percentage is not None:
            rollout_percentage_section = FEATURE_FLAG_ROLLOUT_PERCENTAGE_TEMPLATE.format(
                rollout_percentage=flag.rollout_percentage
            )

        variants_section = ""
        release_conditions_section = ""

        if flag.filters:
            filters = flag.filters

            if filters.get("multivariate"):
                variants = filters["multivariate"].get("variants", [])
                if variants:
                    variants_list = "\n".join(
                        f"- {v.get('key', 'unknown')}: {v.get('rollout_percentage', 0)}%" for v in variants
                    )
                    variants_section = FEATURE_FLAG_VARIANTS_TEMPLATE.format(variants_list=variants_list)

            groups = filters.get("groups", [])
            if groups:
                conditions_list = []
                for i, group in enumerate(groups):
                    rollout = group.get("rollout_percentage")
                    properties = group.get("properties", [])
                    rollout_str = f"{rollout}%" if rollout is not None else "100%"
                    conditions_list.append(
                        f"- Group {i + 1}: {rollout_str} rollout, {len(properties)} property filter(s)"
                    )

                release_conditions_section = FEATURE_FLAG_RELEASE_CONDITIONS_TEMPLATE.format(
                    groups_count=len(groups),
                    conditions_list="\n".join(conditions_list),
                )

        return FEATURE_FLAG_CONTEXT_TEMPLATE.format(
            flag_key=flag.key,
            flag_id=flag.id,
            flag_name=flag.name or "No description",
            flag_active=flag.active,
            flag_created_at=flag.created_at.isoformat() if flag.created_at else "Unknown",
            rollout_percentage_section=rollout_percentage_section,
            variants_section=variants_section,
            release_conditions_section=release_conditions_section,
        ).strip()

    async def execute_and_format(self) -> str:
        """
        Fetch and format the feature flag for AI consumption.

        Returns a formatted string with all feature flag context.
        """
        flag = await self.aget_feature_flag()
        if flag is None:
            return self.get_not_found_message()

        return await self.format_feature_flag(flag)
