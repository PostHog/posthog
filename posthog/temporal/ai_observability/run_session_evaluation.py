"""Session-level evaluation: fetch, payload caps, Hog globals and judge transcript.

Sits beside `run_trace_evaluation` rather than inside it because the shared post-settle
activities still live there (see the spec's deferred module move) and a session module that
imported them while they imported it back would be a cycle. The settle phase and the emit
activity are shared; only the fetch-and-evaluate half is session-specific.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.schema import DateRange, LLMTrace, SessionQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.session_query_runner import SessionQueryRunner
from posthog.models.team import Team
from posthog.temporal.ai_observability.evaluation_hog import build_hog_event_global, hog_bytecode_references_global
from posthog.temporal.ai_observability.evaluation_llm_judge import get_output_type_config
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.run_trace_evaluation import TRACE_EVENTS_LOOKBACK

from products.ai_observability.backend.models.evaluation_configs import MAX_SESSION_EVAL_EVENTS
from products.ai_observability.backend.text_repr.formatters import (
    FormatterOptions,
    format_trace_text_repr,
    llm_trace_to_formatter_format,
)

# Sessions run ~3.5x a trace at p90 (222 events against a trace's typical handful) and the shared
# formatter uniformly samples lines rather than truncating, so the trace's 150k budget would hand
# the judge a shredded transcript. 500k chars is ~2.2k chars per event at p90.
JUDGE_SESSION_MAX_CHARS = 500_000

# Floor so a session with many traces still renders each one readably instead of one line each.
_MIN_TRACE_CHARS_IN_SESSION = 2_000

_SESSION_SKIP_REASONING = {
    "session_not_found": "No session events were found within the evaluation window; evaluation skipped.",
    "session_too_large": (
        f"Session exceeds {MAX_SESSION_EVAL_EVENTS} events — likely a shared or runaway session id; evaluation skipped."
    ),
    "session_expired": (
        "The session aged past the AI events retention window before it could be evaluated; evaluation skipped."
    ),
}

# Structural activity only, matching the settle poll: $ai_evaluation / $ai_feedback / $ai_metric
# are post-hoc annotations and are not part of the unit under evaluation.
_SESSION_EVENT_COUNT_SQL = """
SELECT count() AS event_count
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_trace')
  AND session_id = {session_id}
  AND timestamp >= {date_from}
  AND timestamp <= {date_to}
"""


def session_fetch_lookback(max_age_seconds: int) -> timedelta:
    """How far back from the workflow start to look for session events.

    A session can have begun well before the evaluation's condition first matched, so the window
    has to cover the whole settle budget rather than the trace path's fixed 24h.
    """
    return max(TRACE_EVENTS_LOOKBACK, timedelta(seconds=max_age_seconds))


@dataclass
class SessionFetchOutcome:
    traces: list[LLMTrace] | None
    skip_reason: str | None
    event_count: int


def _count_session_events(team: Team, session_id: str, date_from: datetime, date_to: datetime) -> int:
    """Cheap preflight so a runaway session id is skipped before pulling its payload.

    `fall_back_to_events=False` and an ungrouped aggregate on purpose: the aggregate always
    returns exactly one row, so query_ai_events's empty-result probe never fires and a session
    that aged out of ai_events can never silently degrade to a stripped events scan.
    """
    result = query_ai_events(
        query=parse_select(_SESSION_EVENT_COUNT_SQL),
        placeholders={
            "session_id": ast.Constant(value=session_id),
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
        },
        team=team,
        query_type="SessionEvaluationEventCount",
        fall_back_to_events=False,
        workload=Workload.OFFLINE,
    )
    return int(result.results[0][0]) if result.results else 0


def fetch_session_for_evaluation(
    team_id: int, session_id: str, window_start: datetime, max_age_seconds: int
) -> SessionFetchOutcome:
    """Fetch every trace of a session for an online evaluation, bounded by the settle budget."""
    team = Team.objects.get(id=team_id)
    date_from = window_start - session_fetch_lookback(max_age_seconds)
    date_to = datetime.now(UTC)

    event_count = _count_session_events(team, session_id, date_from, date_to)
    if event_count == 0:
        return SessionFetchOutcome(traces=None, skip_reason="session_not_found", event_count=0)
    if event_count > MAX_SESSION_EVAL_EVENTS:
        return SessionFetchOutcome(traces=None, skip_reason="session_too_large", event_count=event_count)

    runner = SessionQueryRunner(
        team=team,
        query=SessionQuery(
            sessionId=session_id,
            dateRange=DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat()),
        ),
        for_evaluation=True,
    )
    response = runner.calculate()
    if not response.results:
        return SessionFetchOutcome(traces=None, skip_reason="session_not_found", event_count=event_count)
    return SessionFetchOutcome(traces=list(response.results), skip_reason=None, event_count=event_count)


def build_session_hog_globals(
    traces: list[LLMTrace], session_id: str, *, bytecode: list[Any] | None = None
) -> dict[str, Any]:
    """Build Hog globals for a session-level eval.

    Only the target-independent globals (`target`, `evaluation_events`) are built. The
    trace-only `events` / `trace` globals exist for Hog source saved before those two landed,
    and no such source can exist for a session target.
    """
    globals_dict: dict[str, Any] = {}
    if bytecode is None or hog_bytecode_references_global(bytecode, "target"):
        globals_dict["target"] = {
            "type": "session",
            "id": session_id,
            # Summed per-trace, so this stays "time spent doing AI work", the same thing it means
            # on the generation and trace targets. Session wall-clock is a different number and is
            # derivable from evaluation_events timestamps.
            "total_cost_usd": sum(trace.totalCost or 0 for trace in traces),
            "total_latency_seconds": sum(trace.totalLatency or 0 for trace in traces),
        }
    if bytecode is None or hog_bytecode_references_global(bytecode, "evaluation_events"):
        globals_dict["evaluation_events"] = [
            build_hog_event_global(
                event.event,
                event.properties,
                event_uuid=event.id,
                timestamp=event.createdAt,
            )
            for trace in traces
            for event in (trace.events or [])
        ]
    return globals_dict


def build_session_system_prompt(prompt: str, allows_na: bool) -> str:
    """Session-level variant of `build_trace_system_prompt` — frames the unit under evaluation as
    a multi-trace conversation rather than one execution."""
    config = get_output_type_config(allows_na)
    return f"""You are an evaluator. Evaluate the following AI session — every trace in one \
user's conversation, in order — according to this criteria:

{prompt}

{config.instructions}"""


def format_session_for_judge(traces: list[LLMTrace]) -> str:
    """Render a session as the canonical text representation, one section per trace.

    The char budget is split evenly across traces so one long trace can't crowd the others out,
    which matters for "did the user accomplish their goal" — the answer often lives in the
    opening and closing turns, not the biggest one.
    """
    if not traces:
        return ""
    per_trace_budget = max(JUDGE_SESSION_MAX_CHARS // len(traces), _MIN_TRACE_CHARS_IN_SESSION)
    options: FormatterOptions = {
        "include_markers": False,
        "collapsed": False,
        "truncated": True,
        "include_line_numbers": True,
        "max_length": per_trace_budget,
    }
    sections: list[str] = []
    for index, trace in enumerate(traces, start=1):
        trace_dict, hierarchy = llm_trace_to_formatter_format(trace)
        text, _ = format_trace_text_repr(trace_dict, hierarchy, options)
        sections.append(f"=== Trace {index} of {len(traces)} (id: {trace.id}) ===\n{text}")
    return "\n\n".join(sections)[:JUDGE_SESSION_MAX_CHARS]


def build_session_skip_result(allows_na: bool, skip_reason: str) -> EvaluationActivityResult:
    """Session mirror of `_build_trace_skip_result` — no LLM call is made, so model/provider are
    omitted and downstream cost attribution stays clean."""
    result: EvaluationActivityResult = {
        "result_type": "boolean",
        "verdict": None if allows_na else False,
        "reasoning": _SESSION_SKIP_REASONING.get(skip_reason, "Evaluation skipped."),
        "allows_na": allows_na,
        "skipped": True,
        "skip_reason": skip_reason,
    }
    if allows_na:
        result["applicable"] = False
    return result
