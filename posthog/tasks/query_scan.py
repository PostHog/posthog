from typing import Any

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.celery_queues import CeleryQueue
from posthog.models.team.team import Team
from posthog.query_scan.job import Execution, QueryScanJob, run_query_scan
from posthog.query_scan.slot import PENDING_TTL_SECONDS
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)


# The queue cache warming uses, so a burst of analyses cannot overwhelm ClickHouse. Advisory, so
# no retry. `expires` matches the pending slot's lifetime, and the time limits sit inside it, so a
# job never outlives its claim.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.ANALYTICS_LIMITED.value,
    expires=PENDING_TTL_SECONDS,
    soft_time_limit=60,
    time_limit=90,
)
@skip_team_scope_audit  # Team is not a team-scoped model
def analyze_query_scan(
    team_id: int,
    cache_key: str,
    executions: list[dict[str, Any]],
    rows_read: int,
    duration_ms: int,
    trigger: str,
    query_kind: str | None,
    open_filters_placeholder: bool,
    insight_id: int | None = None,
    dashboard_id: int | None = None,
    killed: bool = False,
    error_type: str | None = None,
) -> None:
    team = Team.objects.select_related("organization").filter(pk=team_id).first()
    if team is None:
        return
    try:
        run_query_scan(
            QueryScanJob(
                team=team,
                cache_key=cache_key,
                executions=tuple(Execution.from_payload(execution) for execution in executions),
                rows_read=rows_read,
                duration_ms=duration_ms,
                trigger=trigger,
                query_kind=query_kind,
                open_filters_placeholder=open_filters_placeholder,
                insight_id=insight_id,
                dashboard_id=dashboard_id,
                killed=killed,
                error_type=error_type,
            )
        )
    except SoftTimeLimitExceeded:
        # The EXPLAINs ran past the soft limit. Leave the pending slot to expire so the next slow
        # run of this query retries, and never re-raise: the analysis is advisory.
        logger.warning("query_scan_task_soft_timeout", team_id=team_id, cache_key=cache_key)
