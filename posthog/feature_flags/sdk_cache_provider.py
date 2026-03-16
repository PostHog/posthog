from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog
from posthoganalytics.flag_definition_cache import FlagDefinitionCacheData

if TYPE_CHECKING:
    from posthog.storage.hypercache import HyperCache

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
        self._hypercache: Optional[HyperCache] = None

    def _get_hypercache(self):
        """Lazily resolve the hypercache reference.

        The import is deferred because local_evaluation.py triggers a deep
        import chain (cohort.util → hogql → api → ... → cohort.util) that
        causes a circular ImportError when called during AppConfig.ready().
        By caching the reference after the first successful import, subsequent
        calls skip the import entirely.
        """
        if self._hypercache is None:
            from posthog.models.feature_flag.local_evaluation import flag_definitions_hypercache

            self._hypercache = flag_definitions_hypercache
        return self._hypercache

    def get_flag_definitions(self) -> Optional[FlagDefinitionCacheData]:
        try:
            data = self._get_hypercache().get_from_cache(self._team_id)
            if data is not None:
                # Defensive: ensure a valid FlagDefinitionCacheData even if
                # the HyperCache shape drifts in the future.
                return {
                    "flags": data.get("flags", []),
                    "group_type_mapping": data.get("group_type_mapping", {}),
                    "cohorts": data.get("cohorts", {}),
                }
            return None
        except ImportError:
            # Expected during Django startup — local_evaluation.py has a
            # circular import chain through cohort.util that resolves once
            # all modules finish loading. The SDK's next poll cycle will retry.
            logger.debug("hypercache_flag_provider_import_pending", team_id=self._team_id)
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
