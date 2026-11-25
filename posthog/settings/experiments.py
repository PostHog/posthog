import os
from datetime import UTC, datetime

from posthog.run_mode import derive_run_mode
from posthog.settings.base_variables import CLOUD_DEPLOYMENT, DEBUG

# A star import from this module must not add `UTC` to the settings, because Django reads every uppercase name as one.
__all__ = ["EXPERIMENT_EXPOSURE_EVENT_CUTOFF"]

# The time from which ingestion on PostHog Cloud copies every multivariate $feature_flag_called event into
# $experiment_exposure.
_CLOUD_EXPOSURE_EVENT_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def _exposure_event_cutoff(env_value: str | None, cloud_deployment: str | None, debug: bool) -> datetime | None:
    if env_value:
        parsed = datetime.fromisoformat(env_value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return _CLOUD_EXPOSURE_EVENT_CUTOFF if derive_run_mode(cloud_deployment, debug).is_deployed_cloud else None


# An experiment that starts at or after this time counts its default exposure on $experiment_exposure. An earlier
# experiment counts $feature_flag_called together with its $experiment_exposure copy. Only ingestion writes the copy,
# and only when the ingestion services set EXPERIMENT_EXPOSURE_DUPLICATION_TEAMS. Without the copy, an experiment
# after the cutoff counts no exposures. So the value is unset on every deployment other than PostHog Cloud, which
# keeps all of their experiments on $feature_flag_called.
# To change a self-hosted deployment to $experiment_exposure, first set EXPERIMENT_EXPOSURE_DUPLICATION_TEAMS="*" on
# the ingestion services. Then set this variable to an ISO 8601 time after they restarted. A time without an offset
# is UTC.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF: datetime | None = _exposure_event_cutoff(
    os.getenv("EXPERIMENT_EXPOSURE_EVENT_CUTOFF"), CLOUD_DEPLOYMENT, DEBUG
)
