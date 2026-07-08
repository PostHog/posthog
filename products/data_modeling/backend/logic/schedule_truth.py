"""Read-only Temporal schedule inspection for the data_modeling_ops internal API.

Resolves which Temporal schedule covers a data-modeling entity and in what state.
Classification is by the schedule action's workflow name — NOT by the PostHogDagId
search attribute, which v1 per-query schedules also carry when the saved query has
a node.
"""

import asyncio
from typing import Any

from asgiref.sync import async_to_sync
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

DATA_MODELING_RUN_WORKFLOW = "data-modeling-run"
DATA_MODELING_EXECUTE_DAG_WORKFLOW = "data-modeling-execute-dag"

# Bounds concurrent describe RPCs and total candidates per request so one big team
# cannot exhaust the Temporal namespace rate limit.
DESCRIBE_CONCURRENCY = 10
SCHEDULE_CANDIDATE_CAP = 500


def classify_workflow(workflow_name: str | None) -> str:
    if workflow_name == DATA_MODELING_RUN_WORKFLOW:
        return "v1_saved_query"
    if workflow_name == DATA_MODELING_EXECUTE_DAG_WORKFLOW:
        return "v2_dag"
    return "other"


def extract_schedule_info(schedule_id: str, description: Any) -> dict[str, Any]:
    """Flatten a temporalio ScheduleDescription into a JSON-safe dict.

    Reads defensively with getattr: the temporalio dataclasses have grown fields
    across versions and a missing attribute should degrade to null, not 500 an
    ops endpoint.
    """
    schedule = getattr(description, "schedule", None)
    action = getattr(schedule, "action", None)
    spec = getattr(schedule, "spec", None)
    state = getattr(schedule, "state", None)
    info = getattr(description, "info", None)

    workflow_name = getattr(action, "workflow", None)
    jitter = getattr(spec, "jitter", None)

    next_action_times = getattr(info, "next_action_times", None) or []
    recent_actions = []
    for action_result in (getattr(info, "recent_actions", None) or [])[-5:]:
        started = getattr(action_result, "action", None)
        recent_actions.append(
            {
                "scheduled_at": _iso_or_none(getattr(action_result, "scheduled_at", None)),
                "started_at": _iso_or_none(getattr(action_result, "started_at", None)),
                "workflow_id": getattr(started, "workflow_id", None),
                "workflow_run_id": getattr(started, "first_execution_run_id", None),
            }
        )

    search_attributes: dict[str, Any] = {}
    typed_attributes = getattr(getattr(description, "typed_search_attributes", None), "search_attributes", None) or []
    for pair in typed_attributes:
        key_name = getattr(getattr(pair, "key", None), "name", None)
        if key_name:
            search_attributes[key_name] = pair.value

    return {
        "schedule_id": schedule_id,
        "exists": True,
        "workflow_name": workflow_name,
        "kind": classify_workflow(workflow_name),
        "paused": getattr(state, "paused", None),
        "note": getattr(state, "note", None),
        "next_run_at": _iso_or_none(next_action_times[0]) if next_action_times else None,
        "spec": {
            "intervals": [
                str(getattr(interval, "every", None)) for interval in (getattr(spec, "intervals", None) or [])
            ],
            "cron_expressions": list(getattr(spec, "cron_expressions", None) or []),
            "calendar_count": len(getattr(spec, "calendars", None) or []),
            "jitter": str(jitter) if jitter else None,
            "time_zone": getattr(spec, "time_zone_name", None),
        },
        "recent_actions": recent_actions,
        "search_attributes": search_attributes,
    }


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


@async_to_sync
async def describe_schedules(schedule_ids: list[str]) -> dict[str, dict[str, Any] | None]:
    """Describe many schedules concurrently; NOT_FOUND maps to None.

    Called from sync views: under WSGI async_to_sync just runs the loop; under ASGI it
    hops to a fresh thread per call, which is fine at this route's call rate.
    """
    if not schedule_ids:
        return {}

    temporal = await async_connect()
    semaphore = asyncio.Semaphore(DESCRIBE_CONCURRENCY)

    async def describe_one(schedule_id: str) -> tuple[str, dict[str, Any] | None]:
        async with semaphore:
            try:
                description = await temporal.get_schedule_handle(schedule_id).describe()
            except RPCError as error:
                if error.status == RPCStatusCode.NOT_FOUND:
                    return schedule_id, None
                raise
        return schedule_id, extract_schedule_info(schedule_id, description)

    return dict(await asyncio.gather(*(describe_one(schedule_id) for schedule_id in schedule_ids)))
