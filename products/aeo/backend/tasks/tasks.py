"""Scheduled entrypoints for the AEO citation runner.

The dispatcher is double-gated: a team must be in the AEO_CITATION_TEAM_IDS env
allowlist AND have the `aeo-citation-tracking` feature flag enabled. Both are
empty/off by default, so this is a no-op everywhere until deliberately turned
on. Each eligible team gets its own long-running task so one slow team can't
block another and a worker restart only loses one team's in-flight run.
"""

from __future__ import annotations

from django.conf import settings

import structlog
from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.team import Team
from posthog.ph_client import feature_enabled_or_false

from products.aeo.backend.runner import run_citation_checks

logger = structlog.get_logger(__name__)

AEO_CITATION_TRACKING_FLAG = "aeo-citation-tracking"

# A full run is up to 50 prompts x 3 engines of sequential web-search calls
# (typically 10-60s each); four hours gives slow days headroom without letting
# a hung run hold a worker slot indefinitely.
RUN_SOFT_TIME_LIMIT_SECONDS = 4 * 60 * 60
RUN_TIME_LIMIT_SECONDS = RUN_SOFT_TIME_LIMIT_SECONDS + 300


@shared_task(ignore_result=True)
def run_aeo_citation_checks_task() -> None:
    """Beat entrypoint: fan out one runner task per allowlisted, flag-enabled team."""
    for raw_team_id in settings.AEO_CITATION_TEAM_IDS:
        try:
            team = Team.objects.get(id=int(raw_team_id))
        except (Team.DoesNotExist, ValueError):
            logger.warning("aeo_citation_task_unknown_team", team_id=raw_team_id)
            continue
        # No person is behind this scheduled run; the team UUID keeps the flag
        # call well-formed and the organization group lets the flag target teams.
        enabled = feature_enabled_or_false(
            AEO_CITATION_TRACKING_FLAG,
            str(team.uuid),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
        )
        if not enabled:
            logger.info("aeo_citation_task_flag_disabled", team_id=team.id)
            continue
        run_aeo_citation_checks_for_team_task.delay(team.id)


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=RUN_SOFT_TIME_LIMIT_SECONDS,
    time_limit=RUN_TIME_LIMIT_SECONDS,
)
def run_aeo_citation_checks_for_team_task(team_id: int) -> None:
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.warning("aeo_citation_task_unknown_team", team_id=team_id)
        return
    try:
        run_citation_checks(team)
    except Exception:
        logger.exception("aeo_citation_task_failed", team_id=team_id)
