import json
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import requests
import structlog

from posthog.kafka_client.client import ProduceResult
from posthog.plugins.plugin_server_api import WORKFLOWS_STEP_RESUME_JWT_PURPOSE, resume_workflow_step

from products.cdp.backend.internal_events import (
    WORKFLOW_STEP_RESUME_EVENT,
    InternalEventEvent,
    flush_internal_events_producer,
    produce_internal_event,
)

logger = structlog.get_logger(__name__)

RESULT_STRING_CAP = 1500
RESULT_BYTE_CAP = 4096

WorkflowStepResumeStatus = Literal["completed", "failed", "cancelled"]

RESUME_RETRY_DELAYS_SECONDS = (1, 2, 4)
RESUME_EVENT_DELIVERY_TIMEOUT_SECONDS = 10


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def cap_value(value: Any, budget: int) -> Any:
    if isinstance(value, str):
        lower, upper = 0, min(len(value), RESULT_STRING_CAP)
        while lower < upper:
            midpoint = (lower + upper + 1) // 2
            if _json_size(value[:midpoint]) <= budget:
                lower = midpoint
            else:
                upper = midpoint - 1
        return value[:lower] if budget >= 2 else None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            available = budget - _json_size({**result, key: None}) + 4
            if available <= 0:
                break
            # An explicit null stays, so every answer reaches the step with the same keys.
            if item is None:
                if available >= len("null"):
                    result[key] = None
                continue
            capped = cap_value(item, available)
            if capped is not None and _json_size(capped) <= available:
                result[key] = capped
        return result
    if isinstance(value, list):
        items: list[Any] = []
        for item in value:
            available = budget - _json_size(items) - bool(items)
            capped = cap_value(item, available)
            if capped is None or _json_size(capped) > available or (isinstance(item, str) and capped != item):
                break
            items.append(capped)
        return items
    return value if value is not None and _json_size(value) <= budget else None


class WorkflowStepResumeNotTaken(Exception):
    """The engine still held the step after every retry, or the internal event was not delivered."""


def produce_step_resume_event(
    *, team_id: int, origin_key: str, status: str, result: Mapping[str, Any]
) -> ProduceResult:
    return produce_internal_event(
        team_id=team_id,
        event=InternalEventEvent(
            event=WORKFLOW_STEP_RESUME_EVENT,
            distinct_id=f"team_{team_id}",
            properties={"origin_key": origin_key, "status": status, "result": result},
        ),
    )


def _post_resume(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: dict[str, Any],
    retry_delays: Sequence[float],
) -> bool:
    """POST the wake. False when the worker still held the step on every attempt.

    Only a 409 is retried: the worker holds the job until the step parks. A 200 is final, including
    `stale_key`, which means the step has already moved past this wake.
    """
    for delay in (0, *retry_delays):
        if delay:
            time.sleep(delay)
        response = resume_workflow_step(team_id=team_id, origin_key=origin_key, status=status, result=result)
        if response.status_code != 409:
            response.raise_for_status()
            return True
    logger.info("workflow_step_resume_not_parked", team_id=team_id, origin_key=origin_key)
    return False


def emit_workflow_step_resume(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
    retry_delays: Sequence[float] | None = None,
) -> None:
    """Wake the step which dispatched `origin_key`: a POST to the engine's API with the key
    provisioned, else the `$workflow_step_resume` internal event. A step that has not parked yet
    gets a few short retries. With `raise_on_error` a wake that is not acknowledged raises instead,
    and the caller retries it on its own schedule, so by default it gets no retries in place."""
    if retry_delays is None:
        retry_delays = () if raise_on_error else RESUME_RETRY_DELAYS_SECONDS
    capped = cap_value(result or {}, RESULT_BYTE_CAP)
    try:
        if WORKFLOWS_STEP_RESUME_JWT_PURPOSE.enabled():
            try:
                if _post_resume(
                    team_id=team_id, origin_key=origin_key, status=status, result=capped, retry_delays=retry_delays
                ):
                    return
                if raise_on_error:
                    raise WorkflowStepResumeNotTaken(origin_key)
                return
            except requests.RequestException:
                logger.exception("workflow_step_resume_post_failed", team_id=team_id, origin_key=origin_key)
        produced = produce_step_resume_event(team_id=team_id, origin_key=origin_key, status=status, result=capped)
        if raise_on_error:
            flush_internal_events_producer(RESUME_EVENT_DELIVERY_TIMEOUT_SECONDS)
            if not produced.done():
                raise WorkflowStepResumeNotTaken(origin_key)
            produced.get(timeout=0)
    except Exception:
        logger.exception("workflow_step_resume_emit_failed", team_id=team_id, origin_key=origin_key, status=status)
        if raise_on_error:
            raise
