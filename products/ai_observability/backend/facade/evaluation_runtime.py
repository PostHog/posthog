"""Facade re-export for the evaluation helpers the legacy workflows in ``posthog/temporal/ai_observability`` share.

Product code measures evaluations with these same helpers, so both sides grade a unit identically.
"""

from products.ai_observability.backend.logic.consent import consented_team_ids
from products.ai_observability.backend.logic.evaluations.event_io import extract_event_io
from products.ai_observability.backend.logic.evaluations.hog_runtime import (
    build_hog_event_global,
    build_trace_hog_globals,
    coerce_hog_io_value,
    execute_hog_eval_bytecode,
    hog_bytecode_references_global,
)
from products.ai_observability.backend.logic.evaluations.judge_limits import (
    JUDGE_SESSION_MAX_CHARS,
    JUDGE_TRACE_MAX_CHARS,
)
from products.ai_observability.backend.logic.evaluations.settle import (
    INGESTION_LAG_MARGIN_SECONDS,
    SettlePlan,
    resolve_settle_plan,
    settle_horizon,
)
from products.ai_observability.backend.logic.message_utils import (
    extract_content_text,
    extract_text_from_messages,
    format_tool_definitions,
    last_message_text,
)

__all__ = [
    "INGESTION_LAG_MARGIN_SECONDS",
    "JUDGE_SESSION_MAX_CHARS",
    "JUDGE_TRACE_MAX_CHARS",
    "SettlePlan",
    "build_hog_event_global",
    "build_trace_hog_globals",
    "coerce_hog_io_value",
    "consented_team_ids",
    "execute_hog_eval_bytecode",
    "extract_content_text",
    "extract_event_io",
    "extract_text_from_messages",
    "format_tool_definitions",
    "hog_bytecode_references_global",
    "last_message_text",
    "resolve_settle_plan",
    "settle_horizon",
]
