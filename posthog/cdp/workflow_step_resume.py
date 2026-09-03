from collections.abc import Mapping
from typing import Any, Literal

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

logger = structlog.get_logger(__name__)

WORKFLOW_STEP_RESUME_EVENT = "$workflow_step_resume"

# Workflow variables are capped at 5KB in total.
RESULT_STRING_CAP = 1500

WorkflowStepResumeStatus = Literal["completed", "failed", "cancelled"]


def _cap_strings(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[:RESULT_STRING_CAP] if isinstance(value, str) else value
        for key, value in result.items()
        if value is not None
    }


def resume_workflow_step(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: Mapping[str, Any] | None = None,
) -> None:
    """Wake the step that dispatched `origin_key`. Never raises: a lost wake must not mask the status write."""
    try:
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=WORKFLOW_STEP_RESUME_EVENT,
                distinct_id=f"team_{team_id}",
                properties={"origin_key": origin_key, "status": status, "result": _cap_strings(result or {})},
            ),
        )
    except Exception:
        logger.exception("workflow_step_resume_emit_failed", team_id=team_id, origin_key=origin_key, status=status)
