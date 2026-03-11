from typing import Optional

import structlog
from posthoganalytics.flag_definition_cache import FlagDefinitionCacheData, FlagDefinitionCacheProvider

logger = structlog.get_logger(__name__)


class HyperCacheFlagProvider:
    """
    Read-only FlagDefinitionCacheProvider that reads flag definitions from the
    existing HyperCache infrastructure instead of polling the API.

    The HyperCache is kept fresh via Django signals (when flags/cohorts change)
    and periodic refresh tasks. This provider eliminates per-process API polling
    by reading directly from the same Redis cache.
    """

    def __init__(self, team_id: int):
        self._team_id = team_id

    def get_flag_definitions(self) -> Optional[FlagDefinitionCacheData]:
        try:
            from posthog.models.feature_flag.local_evaluation import flag_definitions_hypercache

            data = flag_definitions_hypercache.get_from_cache(self._team_id)
            if data is not None:
                return {
                    "flags": data.get("flags", []),
                    "group_type_mapping": data.get("group_type_mapping", {}),
                    "cohorts": data.get("cohorts", {}),
                }
            return None
        except Exception:
            logger.exception("hypercache_flag_provider_read_error", team_id=self._team_id)
            return None

    def should_fetch_flag_definitions(self) -> bool:
        # Never poll the API — HyperCache handles all writes via Django signals
        # and periodic refresh tasks
        return False

    def on_flag_definitions_received(self, data: FlagDefinitionCacheData) -> None:
        pass  # No-op — should_fetch always returns False, so this is never called

    def shutdown(self) -> None:
        pass  # No-op — no locks or resources to release


# Runtime check that the class implements the protocol
assert isinstance(HyperCacheFlagProvider(team_id=0), FlagDefinitionCacheProvider)
