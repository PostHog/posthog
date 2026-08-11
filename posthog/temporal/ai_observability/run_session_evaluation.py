"""Session-level evaluation: fetch, payload caps, Hog globals and judge transcript.

Sits beside `run_trace_evaluation` rather than inside it because the shared emit activity lives
there, and this module already imports a constant from it; if `run_trace_evaluation` ever imported
something back from here, the two would cycle. The settle phase and the emit activity are shared;
only the fetch-and-evaluate half is session-specific.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import temporalio
import posthoganalytics
from temporalio.exceptions import ApplicationError

from posthog.schema import DateRange, LLMTrace, SessionQuery

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_TRACES_LIMIT_EXPORT
from posthog.hogql.parser import parse_select

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.hogql_queries.ai.session_query_runner import SessionQueryRunner
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_hog import (
    build_hog_event_global,
    execute_hog_eval_bytecode,
    finalize_hog_eval_result,
    hog_bytecode_references_global,
)
from posthog.temporal.ai_observability.evaluation_llm_judge import call_llm_judge, get_output_type_config
from posthog.temporal.ai_observability.evaluation_payload import (
    PAYLOAD_BYTES_EXPR,
    payload_budget_bytes,
    should_skip_for_payload,
)
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.message_utils import extract_text_from_messages
from posthog.temporal.ai_observability.run_trace_evaluation import TRACE_EVENTS_LOOKBACK
from posthog.temporal.common.utils import close_db_connections

from products.ai_observability.backend.models.evaluation_configs import (
    EVALUATION_TEST_LOOKBACK_DAYS,
    MAX_SESSION_EVAL_EVENTS,
)
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
    "session_has_no_traces": (
        "This session's events have no trace id, so there was nothing to evaluate. Set $ai_trace_id "
        "on the events you want graded."
    ),
    # Two reasons, not one: the remedies differ. Too many events is almost always a shared session
    # id; too much payload is a normal-length session carrying very large inputs or outputs.
    "session_too_large": (
        f"This session holds more than {MAX_SESSION_EVAL_EVENTS} events, which is more than one evaluation can "
        "read. This usually means one session id is shared across several conversations, so give each "
        "conversation its own $ai_session_id."
    ),
    "session_payload_too_large": (
        "This session's events carry more data than one evaluation can hold, so it was not graded. Trim the "
        "largest inputs and outputs, or evaluate each trace instead."
    ),
    "session_truncated": (
        f"This session has more than {MAX_SELECT_TRACES_LIMIT_EXPORT} traces, which is more than one evaluation "
        "can read, so it was not graded."
    ),
    "session_too_long_to_judge": (
        "This session's transcript is too long to grade in one piece. A Hog evaluation has no transcript limit, "
        "or you can evaluate each trace instead."
    ),
}

# Mirrors `ai_events.retention_days`, whose DEFAULT 30 nothing currently overrides — the column
# exists for per-row retention that no ingestion path writes yet. Keep them in step: if retention
# ever becomes longer than this, the fetch would stop at 30 days and grade a session on its tail
# with no way to notice, because events past their drop_date are deleted and leave nothing to
# count. That case is undetectable from here by construction, which is why the constant matters.
AI_EVENTS_RETENTION_DAYS = 30

# Must select exactly the rows `SessionQueryRunner` will read, or the cap it gates bounds nothing.
# Two ways the fetch is wider than a naive `session_id = X` count, both deliberate over there:
# it reads six event types (annotations included, unlike the settle poll, where they correctly
# don't count as liveness), and it resolves traces first, then reads every event of those traces
# — `session_id` is per-event and nullable, so a producer that tags only the trace root would
# otherwise preflight at 1 and fetch the whole trace. minOrNull(timestamp) rides the same scan,
# and over this row set it means the session's real start rather than its first tagged event.
_SESSION_EVENT_COUNT_SQL = """
SELECT count() AS event_count, minOrNull(timestamp) AS first_seen
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
  AND isNotNull(trace_id)
  AND trace_id != ''
  AND trace_id IN (
      SELECT trace_id
      FROM posthog.ai_events AS ai_events
      WHERE session_id = {session_id}
        AND isNotNull(trace_id)
        AND trace_id != ''
        AND timestamp >= {date_from}
        AND timestamp <= {date_to}
  )
  AND timestamp >= {date_from}
  AND timestamp <= {date_to}
"""


# Deliberately a second query rather than another aggregate on the count's scan: summing lengths
# forces ClickHouse to decompress the payload columns, and a runaway session id should be rejected
# by the count without ever paying for that. Only sessions that already look plausible get here.
_SESSION_PAYLOAD_BYTES_SQL = f"""
SELECT {PAYLOAD_BYTES_EXPR} AS payload_bytes
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
  AND isNotNull(trace_id)
  AND trace_id != ''
  AND trace_id IN (
      SELECT trace_id
      FROM posthog.ai_events AS ai_events
      WHERE session_id = {{session_id}}
        AND isNotNull(trace_id)
        AND trace_id != ''
        AND timestamp >= {{date_from}}
        AND timestamp <= {{date_to}}
  )
  AND timestamp >= {{date_from}}
  AND timestamp <= {{date_to}}
"""


def _sum_session_payload_bytes(team: Team, session_id: str, date_from: datetime, date_to: datetime) -> int:
    with tags_context(product=Product.LLM_ANALYTICS):
        result = query_ai_events(
            query=parse_select(_SESSION_PAYLOAD_BYTES_SQL),
            placeholders={
                "session_id": ast.Constant(value=session_id),
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
            },
            team=team,
            query_type="SessionEvaluationPayloadBytes",
            fall_back_to_events=False,
            workload=Workload.OFFLINE,
        )
    if not result.results:
        return 0
    return int(result.results[0][0] or 0)


def session_fetch_lookback(max_age_seconds: int) -> timedelta:
    """How far back the settle poll's liveness/runaway-count check searches for recent activity.

    Not used for the fetch's own `date_from`: `max_age_seconds` is a forward budget (how long the
    workflow waits after the first matching generation), which says nothing about how long the
    session was already running, so `fetch_session_for_evaluation` derives its window from the
    session's actual first event instead. This lookback only needs to cover the settle window
    itself, which is what `check_session_settled_activity` uses it for.
    """
    return max(TRACE_EVENTS_LOOKBACK, timedelta(seconds=max_age_seconds))


@dataclass
class SessionFetchOutcome:
    traces: list[LLMTrace] | None
    skip_reason: str | None
    event_count: int


@dataclass
class _SessionEventCount:
    event_count: int
    first_seen: datetime | None


def _count_session_events(team: Team, session_id: str, date_from: datetime, date_to: datetime) -> _SessionEventCount:
    """Cheap preflight so a runaway session id is skipped before pulling its payload, and the
    source of the session's real start time (see `fetch_session_for_evaluation`).

    `fall_back_to_events=False` and an ungrouped aggregate on purpose: the aggregate always
    returns exactly one row, so query_ai_events's empty-result probe never fires and a session
    that aged out of ai_events can never silently degrade to a stripped events scan.
    """
    with tags_context(product=Product.LLM_ANALYTICS):
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
    if not result.results:
        return _SessionEventCount(event_count=0, first_seen=None)
    event_count, first_seen = result.results[0]
    return _SessionEventCount(event_count=int(event_count), first_seen=first_seen)


def fetch_session_for_evaluation(team_id: int, session_id: str, window_start: datetime) -> SessionFetchOutcome:
    """Fetch every trace of a session for an online evaluation, bounded by retention.

    Deliberately not bounded by `max_age_seconds`: that's a forward budget (how long the workflow
    waits after the first matching generation), which says nothing about how long the session had
    already been running when that generation arrived. So the initial preflight searches back to
    the full retention window instead of guessing a lookback from `max_age_seconds`, reads the
    session's real start time off the same scan (`minOrNull(timestamp)`, free per the comment on
    `_SESSION_EVENT_COUNT_SQL`), and narrows `date_from` to that start for the actual fetch.
    Retention is the floor: a session that began before it can't be fetched whole no matter what
    window is chosen.
    """
    team = Team.objects.get(id=team_id)
    retention_floor = window_start - timedelta(days=AI_EVENTS_RETENTION_DAYS)
    date_to = datetime.now(UTC)

    preflight = _count_session_events(team, session_id, retention_floor, date_to)
    if preflight.event_count == 0:
        return SessionFetchOutcome(traces=None, skip_reason="session_not_found", event_count=0)
    if preflight.event_count > MAX_SESSION_EVAL_EVENTS:
        return SessionFetchOutcome(traces=None, skip_reason="session_too_large", event_count=preflight.event_count)

    # Only now that the row count looks plausible is it worth reading the payload columns to size it.
    payload_bytes = _sum_session_payload_bytes(team, session_id, retention_floor, date_to)
    if should_skip_for_payload(
        target="session",
        payload_bytes=payload_bytes,
        budget_bytes=payload_budget_bytes(JUDGE_SESSION_MAX_CHARS),
    ):
        return SessionFetchOutcome(
            traces=None, skip_reason="session_payload_too_large", event_count=preflight.event_count
        )

    event_count = preflight.event_count
    date_from = preflight.first_seen or retention_floor
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=UTC)
    date_from = max(date_from, retention_floor)

    runner = SessionQueryRunner(
        team=team,
        query=SessionQuery(
            sessionId=session_id,
            dateRange=DateRange(date_from=date_from.isoformat(), date_to=date_to.isoformat()),
            # SessionQueryRunner defaults to DEFAULT_RETURNED_ROWS (100) under LimitContext.QUERY,
            # which would silently drop the tail of any session past 100 traces. Ask for the same
            # ceiling MAX_SESSION_EVAL_EVENTS already implies is plausible for a real session.
            limit=MAX_SELECT_TRACES_LIMIT_EXPORT,
        ),
        for_evaluation=True,
    )
    response = runner.calculate()
    if not response.results:
        # The preflight counted rows, so events exist — the runner requires a non-empty trace id and
        # found none. Saying "no session events were found" here would send the user looking in the
        # wrong place.
        return SessionFetchOutcome(traces=None, skip_reason="session_has_no_traces", event_count=event_count)
    if response.hasMore:
        # A session graded on part of itself must not look like a session graded whole, so skip
        # rather than hand the judge a transcript silently missing its tail (or, combined with
        # the runner's newest-first ordering, its opening).
        return SessionFetchOutcome(traces=None, skip_reason="session_truncated", event_count=event_count)

    traces = sorted(response.results, key=lambda trace: trace.createdAt)
    return SessionFetchOutcome(traces=traces, skip_reason=None, event_count=event_count)


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


def format_session_for_judge(traces: list[LLMTrace]) -> str | None:
    """Render a session as the canonical text representation, one section per trace.

    The char budget is split evenly across traces so one long trace can't crowd the others out,
    which matters for "did the user accomplish their goal" — the answer often lives in the
    opening and closing turns, not the biggest one.

    Returns `None` only when the *rendered* transcript overshoots the budget, meaning a final slice
    would silently drop trailing traces. The caller must treat that as a `session_too_long_to_judge`
    skip rather than judge a transcript that's missing its close.

    Deliberately measured after rendering rather than from `per_trace_budget * len(traces)`: the
    per-trace budget is a ceiling, not a prediction, and real traces render well under it. Deciding
    on the product turned this into a hard cliff at 251 traces regardless of how little those traces
    actually contained.
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
    rendered = "\n\n".join(sections)
    if len(rendered) > JUDGE_SESSION_MAX_CHARS:
        return None
    return rendered


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


@dataclass
class ExecuteSessionEvaluationInputs:
    evaluation: dict[str, Any]
    team_id: int
    session_id: str
    window_start: str

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "evaluation_id": self.evaluation.get("id"),
            "session_id": self.session_id,
        }


@temporalio.activity.defn
@close_db_connections
@posthoganalytics.scoped()
def execute_session_llm_judge_activity(inputs: ExecuteSessionEvaluationInputs) -> EvaluationActivityResult:
    """Fetch the whole session and run the LLM judge over its transcript.

    Fetch and judge happen in one activity on purpose: returning the session through the
    workflow would hit Temporal's ~2 MiB payload limit.
    """
    evaluation = inputs.evaluation

    if evaluation["evaluation_type"] != "llm_judge":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    prompt = evaluation.get("evaluation_config", {}).get("prompt")
    if not prompt:
        raise ApplicationError("Missing prompt in evaluation_config", non_retryable=True)

    if evaluation["output_type"] != "boolean":
        raise ApplicationError(
            f"Unsupported output type: {evaluation['output_type']}. Supported types: 'boolean'.",
            non_retryable=True,
        )

    allows_na = evaluation.get("output_config", {}).get("allows_na", False)

    outcome = fetch_session_for_evaluation(
        inputs.team_id,
        inputs.session_id,
        datetime.fromisoformat(inputs.window_start),
    )
    if outcome.skip_reason or outcome.traces is None:
        return build_session_skip_result(allows_na, outcome.skip_reason or "session_not_found")

    transcript = format_session_for_judge(outcome.traces)
    if transcript is None:
        return build_session_skip_result(allows_na, "session_too_long_to_judge")

    return call_llm_judge(
        evaluation=evaluation,
        system_prompt=build_session_system_prompt(prompt, allows_na),
        user_prompt=transcript,
        allows_na=allows_na,
    )


@temporalio.activity.defn
async def execute_session_hog_eval_activity(inputs: ExecuteSessionEvaluationInputs) -> EvaluationActivityResult:
    """Fetch the whole session and run Hog bytecode against session-level globals."""
    evaluation = inputs.evaluation

    if evaluation["evaluation_type"] != "hog":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    bytecode = evaluation.get("evaluation_config", {}).get("bytecode")
    if not bytecode:
        raise ApplicationError("Missing bytecode in evaluation_config", non_retryable=True)

    allows_na = evaluation.get("output_config", {}).get("allows_na", False)

    def _execute() -> tuple[dict[str, Any] | None, str | None]:
        outcome = fetch_session_for_evaluation(
            inputs.team_id,
            inputs.session_id,
            datetime.fromisoformat(inputs.window_start),
        )
        if outcome.skip_reason or outcome.traces is None:
            return None, outcome.skip_reason or "session_not_found"
        globals_dict = build_session_hog_globals(outcome.traces, inputs.session_id, bytecode=bytecode)
        return execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=allows_na), None

    result, skip_reason = await database_sync_to_async(_execute, thread_sensitive=False)()

    if skip_reason or result is None:
        return build_session_skip_result(allows_na, skip_reason or "session_not_found")

    return finalize_hog_eval_result(result, evaluation=evaluation, allows_na=allows_na, unit_label="session")


@dataclass
class SessionHogTestResult:
    """One session's outcome from `run_hog_eval_over_recent_sessions`, shaped for the editor test
    endpoint rather than for online emission."""

    session_id: str
    verdict: bool | None
    reasoning: str
    error: str | None
    input_preview: str
    output_preview: str


# Sessions whose structural activity has been quiet for the configured period, restricted to those
# with a generation matching the evaluation's conditions. At a long quiet period the sample is
# legitimately empty, and the caller says so rather than widening the window and previewing sessions
# the evaluation has not reached yet.
#
# Quiet is judged on `timestamp` here, not the `_timestamp` arrival clock the online settle poll
# uses. Not a preference: any query that can return zero rows is also compiled against the shared
# events table — as a fallback, or as the retention probe that classifies a miss — and `_timestamp`
# does not exist there, so a `_timestamp` predicate makes the empty sample a hard error rather than
# an empty list. The settle poll escapes this only because its ungrouped aggregate always returns a
# row. The cost is that a client clock running fast can make a session look quiet a little early in
# the preview; the online settle is unaffected and still judges on arrival.
_SESSION_TEST_SAMPLE_SQL = """
SELECT session_id, min(timestamp) AS trigger_timestamp, max(timestamp) AS last_seen
FROM posthog.ai_events AS ai_events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
  AND isNotNull(session_id)
  AND session_id != ''
  AND timestamp >= {date_from}
  AND timestamp <= {date_to}
  AND session_id IN (
      SELECT session_id
      FROM posthog.ai_events AS ai_events
      WHERE event = '$ai_generation'
        AND isNotNull(session_id)
        AND session_id != ''
        AND timestamp >= {date_from}
        AND timestamp <= {date_to}
        AND {condition_filter}
  )
GROUP BY session_id
HAVING last_seen <= {quiet_cutoff}
ORDER BY last_seen DESC
LIMIT {sample_count}
"""


def _sample_quiet_sessions(
    team: Team,
    condition_filter: ast.Expr | None,
    sample_count: int,
    date_from: datetime,
    date_to: datetime,
    quiet_cutoff: datetime,
) -> list[str]:
    with tags_context(product=Product.LLM_ANALYTICS):
        response = query_ai_events(
            query=parse_select(_SESSION_TEST_SAMPLE_SQL),
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
                "quiet_cutoff": ast.Constant(value=quiet_cutoff),
                "sample_count": ast.Constant(value=sample_count),
                "condition_filter": condition_filter if condition_filter is not None else ast.Constant(value=True),
            },
            team=team,
            query_type="EvaluationTestHogSessionSample",
            fall_back_to_events=True,
        )
    return [str(row[0]) for row in (response.results or [])]


def _session_io_preview(traces: list[LLMTrace]) -> tuple[str, str]:
    """First input of the session's opening trace and last output of its closing one. The Hog body
    still sees the whole session; this is only for display."""
    input_preview = ""
    output_preview = ""
    for trace in traces:
        for event in trace.events or []:
            io = extract_event_io(event.event, event.properties)
            if not input_preview:
                input_preview = extract_text_from_messages(io.input_raw)[:200]
            output_text = extract_text_from_messages(io.output_raw)[:200]
            if output_text:
                output_preview = output_text
    return input_preview, output_preview


def run_hog_eval_over_recent_sessions(
    *,
    team: Team,
    bytecode: list[Any],
    condition_filter: ast.Expr | None,
    sample_count: int,
    allows_na: bool,
    quiet_period_seconds: int,
    lookback_days: int = EVALUATION_TEST_LOOKBACK_DAYS,
) -> list[SessionHogTestResult]:
    """Sample sessions that have gone quiet and run session-level Hog bytecode against each.

    The session mirror of `run_hog_eval_over_recent_traces`, so the editor preview matches how a
    session evaluation runs online — whole session, session globals — rather than against one
    generation or one trace. Each sampled session is fetched in full; `sample_count` is lower than
    the trace path's because a session fetch is a whole conversation rather than a single trace.
    """
    now = datetime.now(UTC)
    quiet_cutoff = now - timedelta(seconds=quiet_period_seconds)
    date_from = now - timedelta(days=lookback_days)
    session_ids = _sample_quiet_sessions(team, condition_filter, sample_count, date_from, now, quiet_cutoff)

    results: list[SessionHogTestResult] = []
    for session_id in session_ids:
        outcome = fetch_session_for_evaluation(team.pk, session_id, now)
        if outcome.skip_reason or outcome.traces is None:
            results.append(
                SessionHogTestResult(
                    session_id=session_id,
                    verdict=None,
                    reasoning="",
                    error=_SESSION_SKIP_REASONING.get(
                        outcome.skip_reason or "session_not_found", "Evaluation skipped."
                    ),
                    input_preview="",
                    output_preview="",
                )
            )
            continue

        globals_dict = build_session_hog_globals(outcome.traces, session_id, bytecode=bytecode)
        hog_result = execute_hog_eval_bytecode(bytecode, globals_dict, allows_na=allows_na)
        input_preview, output_preview = _session_io_preview(outcome.traces)
        results.append(
            SessionHogTestResult(
                session_id=session_id,
                verdict=hog_result.get("verdict"),
                reasoning=hog_result.get("reasoning") or "",
                error=hog_result.get("error"),
                input_preview=input_preview,
                output_preview=output_preview,
            )
        )
    return results
