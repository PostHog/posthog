"""Feature-flag gate for the APM product.

APM is unreleased. Nothing it does should run for a team until
``apm-anomaly-detection`` is switched on for that team, so every entry point
routes through this module and the rollout has exactly one switch to audit.

The gate evaluates against the ``project`` group keyed on team ID alone, so it
needs no ``Team`` row and no database read. That matters because the detector is
designed to run per team on a schedule, where a fetch per team per tick would be
pure overhead.
"""

from __future__ import annotations

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

APM_ANOMALY_DETECTION_FLAG = "apm-anomaly-detection"


def is_anomaly_detection_enabled(team_id: int) -> bool:
    try:
        return feature_enabled_or_false(
            APM_ANOMALY_DETECTION_FLAG,
            str(team_id),
            groups={"project": str(team_id)},
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            # The detector is scheduled per team, so leaving this on would emit a
            # $feature_flag_called event for every team on every tick.
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased product stays off when the flags service is unreachable,
        # rather than defaulting on or failing the caller's run.
        logger.exception("apm_feature_flag_check_failed", team_id=team_id)
        return False
