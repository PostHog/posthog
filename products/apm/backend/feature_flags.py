"""Feature-flag gate for the APM product.

APM is unreleased, so nothing that lands here runs for a team until
``unified-apm-product`` is switched on for that team. This gates the product as
a whole. A capability that needs its own rollout, like anomaly detection, gets
its own flag layered on top of this one rather than reusing it.

The gate always sends the ``project`` group keyed on team ID, so it needs no
``Team`` row and no database read. That matters because work landing here is
expected to run per team on a schedule, where a fetch per team per tick would be
pure overhead. A request made by a user also passes that user's distinct ID and
email, so the flag can target people (for example an internal cohort) as well as
projects. A user who anonymizes their data passes an explicit null email, as the
frontend does, so a stored email cannot match. Scheduled work has no user and
matches only project conditions.
"""

from __future__ import annotations

import structlog

from posthog.ph_client import feature_enabled_or_false

logger = structlog.get_logger(__name__)

UNIFIED_APM_PRODUCT_FLAG = "unified-apm-product"


def is_apm_enabled(team_id: int, *, distinct_id: str | None = None, email: str | None = None) -> bool:
    try:
        return feature_enabled_or_false(
            UNIFIED_APM_PRODUCT_FLAG,
            distinct_id or str(team_id),
            groups={"project": str(team_id)},
            person_properties={"email": email} if distinct_id else None,
            group_properties={"project": {"id": str(team_id)}},
            only_evaluate_locally=False,
            # Work here is scheduled per team, so leaving this on would emit a
            # $feature_flag_called event for every team on every tick.
            send_feature_flag_events=False,
        )
    except Exception:
        # An unreleased product stays off when the flags service is unreachable,
        # rather than defaulting on or failing the caller's run.
        logger.exception("apm_feature_flag_check_failed", team_id=team_id)
        return False
