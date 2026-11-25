import os
from datetime import UTC, datetime

from posthog.run_mode import derive_run_mode
from posthog.settings.base_variables import CLOUD_DEPLOYMENT, DEBUG

# A star import from this module must not add `UTC` to the settings, because Django reads every uppercase name as one.
__all__ = ["EXPERIMENT_EXPOSURE_EVENT_CUTOFF"]

# When ingestion on PostHog Cloud started to copy multivariate $feature_flag_called events into $experiment_exposure.
_CLOUD_EXPOSURE_EVENT_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def _exposure_event_cutoff(env_value: str | None, cloud_deployment: str | None, debug: bool) -> datetime | None:
    if env_value:
        parsed = datetime.fromisoformat(env_value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return _CLOUD_EXPOSURE_EVENT_CUTOFF if derive_run_mode(cloud_deployment, debug).is_deployed_cloud else None


# Experiments that start at or after this time count $experiment_exposure, which ingestion writes only where
# EXPERIMENT_EXPOSURE_DUPLICATION_TEAMS is set. Without it they count no exposures, so only PostHog Cloud has a cutoff.
# To opt in, set EXPERIMENT_EXPOSURE_DUPLICATION_TEAMS="*" on the ingestion services, then set this to an ISO 8601 time
# after they restarted.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF: datetime | None = _exposure_event_cutoff(
    os.getenv("EXPERIMENT_EXPOSURE_EVENT_CUTOFF"), CLOUD_DEPLOYMENT, DEBUG
)
