import json
from collections.abc import Mapping
from typing import Any, Literal

import structlog

from posthog.cdp.internal_events import WORKFLOW_STEP_RESUME_EVENT, InternalEventEvent, produce_internal_event

logger = structlog.get_logger(__name__)

RESULT_STRING_CAP = 1500
RESULT_BYTE_CAP = 4096

WorkflowStepResumeStatus = Literal["completed", "failed", "cancelled"]


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _cap_value(value: Any, budget: int) -> Any:
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
            capped = _cap_value(item, available)
            if capped is not None and _json_size(capped) <= available:
                result[key] = capped
        return result
    if isinstance(value, list):
        items: list[Any] = []
        for item in value:
            available = budget - _json_size(items) - bool(items)
            capped = _cap_value(item, available)
            if capped is None or _json_size(capped) > available or (isinstance(item, str) and capped != item):
                break
            items.append(capped)
        return items
    return value if value is not None and _json_size(value) <= budget else None


def resume_workflow_step(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: Mapping[str, Any] | None = None,
    raise_on_error: bool = False,
) -> None:
    """Wake the step that dispatched `origin_key`; delivery activities can opt into retries."""
    try:
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=WORKFLOW_STEP_RESUME_EVENT,
                distinct_id=f"team_{team_id}",
                properties={
                    "origin_key": origin_key,
                    "status": status,
                    "result": _cap_value(result or {}, RESULT_BYTE_CAP),
                },
            ),
        )
    except Exception:
        logger.exception("workflow_step_resume_emit_failed", team_id=team_id, origin_key=origin_key, status=status)
        if raise_on_error:
            raise
