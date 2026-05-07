import structlog
from celery import shared_task

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.hogql_queries.web_analytics.bot_analytics.warming import warm_bot_analytics_for_team
from posthog.models.team import Team
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

logger = structlog.get_logger(__name__)


@shared_task(
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    ignore_result=True,
    expires=60 * 30,
    autoretry_for=(CHQueryErrorTooManySimultaneousQueries,),
    retry_backoff=2,
    retry_backoff_max=60,
    max_retries=3,
)
def warm_bot_analytics_for_team_task(team_id: int) -> None:
    """Warm bot trends precomputation for a single team.

    Triggered by `schedule_bot_analytics_warming_task` per team so each call
    is cheap, retryable, and isolated. Failures of one team do not block
    other teams.
    """
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        logger.info("bot_analytics_warming_team_not_found", team_id=team_id)
        return

    warm_bot_analytics_for_team(team)


@shared_task(ignore_result=True, expires=60 * 50)
@skip_team_scope_audit
def schedule_bot_analytics_warming_task() -> None:
    """Fan out per-team warming for the bot analytics tab.

    Targets the same `cache-warming` opt-in cohort that the regular insight
    warmer uses, so we don't need a separate enrolment surface. The bot tab
    is most useful for higher-traffic teams already in that cohort.
    """
    from posthog.caching.warming import teams_enabled_for_cache_warming
    from posthog.clickhouse.client.execute import KillSwitchLevel, get_kill_switch_level

    kill_switch_level = get_kill_switch_level()
    if kill_switch_level != KillSwitchLevel.OFF:
        logger.info("bot_analytics_warming_kill_switched", level=kill_switch_level)
        return

    team_ids = teams_enabled_for_cache_warming()
    for team_id in team_ids:
        warm_bot_analytics_for_team_task.delay(team_id)
