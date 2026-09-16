import json
from collections.abc import Mapping
from typing import Any, Literal

import requests
import structlog
from celery import current_app, shared_task

from posthog.cdp.internal_events import WORKFLOW_STEP_RESUME_EVENT, InternalEventEvent, produce_internal_event
from posthog.celery_queues import CeleryQueue
from posthog.plugins.plugin_server_api import WORKFLOWS_STEP_RESUME_JWT_PURPOSE, resume_workflow_step
from posthog.scoping_audit import skip_team_scope_audit

logger = structlog.get_logger(__name__)

STEP_RESUME_DELIVERY_TASK = "posthog.cdp.workflow_step_resume.deliver_workflow_step_resume"

RESULT_STRING_CAP = 1500
RESULT_BYTE_CAP = 4096

WorkflowStepResumeStatus = Literal["completed", "failed", "cancelled"]


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


def emit_workflow_step_resume(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
) -> None:
    """Wake the step which dispatched `origin_key`.

    The wake is asynchronous. This call returns once the delivery is queued, not once the step
    resumes. With the step resume key provisioned, a Celery task posts the wake to the engine's
    API and retries until the parked job takes it; until then the wake is a `$workflow_step_resume`
    internal event the subscription matcher consumes. Delivery activities can opt into retries
    with `raise_on_error`.
    """
    capped = cap_value(result or {}, RESULT_BYTE_CAP)
    try:
        if WORKFLOWS_STEP_RESUME_JWT_PURPOSE.enabled():
            current_app.send_task(
                STEP_RESUME_DELIVERY_TASK,
                kwargs={"team_id": team_id, "origin_key": origin_key, "status": status, "result": capped},
            )
            return
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=WORKFLOW_STEP_RESUME_EVENT,
                distinct_id=f"team_{team_id}",
                properties={"origin_key": origin_key, "status": status, "result": capped},
            ),
        )
    except Exception:
        logger.exception("workflow_step_resume_emit_failed", team_id=team_id, origin_key=origin_key, status=status)
        if raise_on_error:
            raise


# Backoff runs about twelve minutes end to end, well inside the parked step's deadline.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=12,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_backoff_max=120,
)
@skip_team_scope_audit
def deliver_workflow_step_resume(team_id: int, origin_key: str, status: str, result: dict[str, Any]) -> None:
    """One wake over HTTP; a 409 (worker still holds the job) or transport error re-enqueues with backoff."""
    resume_workflow_step(team_id=team_id, origin_key=origin_key, status=status, result=result).raise_for_status()
