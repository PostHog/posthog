"""Celery beat that wakes parked LiveInvestigationWorkflows when probe data has
accumulated. See products/live_debugger/docs/live-investigation-primitive-design.md.

Scans WATCHING investigations, batches one HogQL count per team, and signals each
workflow whose program has reached its min_events threshold. The workflow's
wait_condition timeout is the natural fallback if the beat is down — investigations
will still complete, just on a longer clock.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from asgiref.sync import sync_to_async
from celery import shared_task

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.live_debugger.backend.models import LiveInvestigation

logger = logging.getLogger(__name__)


@shared_task(
    name="posthog.tasks.live_investigations.check_ready_investigations",
    soft_time_limit=120,
    time_limit=180,
    rate_limit="2/m",
)
def check_ready_investigations() -> None:
    asyncio.run(_check_ready_investigations_async())


async def _check_ready_investigations_async() -> None:
    rows = await sync_to_async(_load_watching_investigations, thread_sensitive=False)()
    if not rows:
        return

    by_team: dict[int, list[LiveInvestigation]] = defaultdict(list)
    for row in rows:
        by_team[row.team_id].append(row)

    teams = await sync_to_async(_load_teams, thread_sensitive=False)(list(by_team.keys()))

    temporal_client = await async_connect()

    total_signaled = 0
    for team_id, investigations in by_team.items():
        team = teams.get(team_id)
        if team is None:
            logger.warning("live_investigations.team_missing", extra={"team_id": team_id})
            continue
        try:
            counts = await _count_events_per_program(team, investigations)
        except Exception:
            logger.exception("live_investigations.count_failed", extra={"team_id": team_id})
            continue

        for inv in investigations:
            count = counts.get(str(inv.program_id), 0)
            if count < inv.min_events:
                continue
            try:
                handle = temporal_client.get_workflow_handle(inv.workflow_id)
                await handle.signal("events_ready")
                total_signaled += 1
            except Exception:
                logger.exception(
                    "live_investigations.signal_failed",
                    extra={"investigation_id": str(inv.id), "workflow_id": inv.workflow_id},
                )

    logger.info(
        "live_investigations.beat_run",
        extra={"scanned": len(rows), "signaled": total_signaled},
    )


def _load_watching_investigations() -> list[LiveInvestigation]:
    return list(
        LiveInvestigation.objects.filter(status=LiveInvestigation.Status.WATCHING).only(
            "id", "team_id", "program_id", "min_events", "workflow_id"
        )
    )


def _load_teams(team_ids: list[int]) -> dict[int, Team]:
    return {team.id: team for team in Team.objects.filter(id__in=team_ids)}


async def _count_events_per_program(
    team: Team,
    investigations: list[LiveInvestigation],
) -> dict[str, int]:
    program_ids = [str(inv.program_id) for inv in investigations]
    query = parse_select(
        """
        SELECT JSONExtractString(properties, '$program_id') AS pid, count() AS c
        FROM events
        WHERE event = {event_name}
          AND JSONExtractString(properties, '$program_id') IN {pids}
        GROUP BY pid
        """,
        placeholders={
            "event_name": ast.Constant(value="$data_breakpoint_hit"),
            "pids": ast.Constant(value=program_ids),
        },
    )
    response = await sync_to_async(execute_hogql_query, thread_sensitive=False)(
        query=query,
        team=team,
    )
    return {row[0]: int(row[1]) for row in (response.results or [])}
