"""On-demand sentiment classification workflow.

Computes sentiment for a single trace and returns the result directly
(does NOT emit events). Used by the trace detail view to show sentiment
on-the-fly.
"""

import json
from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Any

import structlog
import temporalio
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

logger = structlog.get_logger(__name__)


@dataclass
class OnDemandSentimentInput:
    team_id: int
    trace_id: str
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class OnDemandSentimentBatchInput:
    team_id: int
    trace_ids: list[str]
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class _PendingClassification:
    trace_id: str
    gen_uuid: str
    msg_index: int
    text: str


_EMPTY_RESULT: dict[str, Any] = {
    "label": "neutral",
    "score": 0.0,
    "scores": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
}


_GENERATIONS_QUERY = """
    SELECT uuid, properties
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= toDateTime({date_from}, 'UTC')
      AND timestamp <= toDateTime({date_to}, 'UTC')
      AND properties.$ai_trace_id = {trace_id}
    ORDER BY timestamp DESC
    LIMIT {max_generations}
"""

_GENERATIONS_BATCH_QUERY = """
    SELECT uuid, properties, properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= toDateTime({date_from}, 'UTC')
      AND timestamp <= toDateTime({date_to}, 'UTC')
      AND properties.$ai_trace_id IN {trace_ids}
    ORDER BY trace_id, timestamp DESC
"""


def _resolve_date_bounds(date_from: str | None, date_to: str | None) -> tuple[str, str]:
    """Resolve caller-provided date strings to concrete timestamps for the query.

    Falls back to a lookback window when no bounds are provided.
    """
    from datetime import datetime

    from posthog.temporal.llm_analytics.sentiment.constants import QUERY_LOOKBACK_DAYS

    now = datetime.now(tz=UTC)
    resolved_from = (
        date_from if date_from else (now - timedelta(days=QUERY_LOOKBACK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    )
    resolved_to = date_to if date_to else now.strftime("%Y-%m-%d %H:%M:%S")
    return resolved_from, resolved_to


@temporalio.activity.defn
async def classify_sentiment_on_demand_activity(input: OnDemandSentimentInput) -> dict[str, Any]:
    """Fetch $ai_generation events for a trace and classify sentiment on each user message."""
    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.models.team import Team
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_GENERATIONS, MAX_TOTAL_CLASSIFICATIONS
    from posthog.temporal.llm_analytics.sentiment.extraction import (
        extract_user_messages_individually,
        truncate_to_token_limit,
    )
    from posthog.temporal.llm_analytics.sentiment.model import classify_batch

    team = Team.objects.get(id=input.team_id)
    resolved_from, resolved_to = _resolve_date_bounds(input.date_from, input.date_to)

    query = parse_select(_GENERATIONS_QUERY)
    result = execute_hogql_query(
        query_type="SentimentOnDemand",
        query=query,
        placeholders={
            "date_from": ast.Constant(value=resolved_from),
            "date_to": ast.Constant(value=resolved_to),
            "trace_id": ast.Constant(value=input.trace_id),
            "max_generations": ast.Constant(value=MAX_GENERATIONS),
        },
        team=team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    if not result.results:
        return {
            "trace_id": input.trace_id,
            **_EMPTY_RESULT,
            "generations": {},
            "generation_count": 0,
            "message_count": 0,
        }

    # Phase 1: collect all texts to classify, respecting the cap
    pending: list[_PendingClassification] = []
    # Track generation ordering so we can reconstruct per-gen results
    gen_uuids_seen: list[str] = []
    cap_hit = False

    for row in result.results:
        event_uuid, raw_props = str(row[0]), row[1]
        props = json.loads(raw_props) if isinstance(raw_props, str) else raw_props

        ai_input = props.get("$ai_input")
        user_messages = extract_user_messages_individually(ai_input)
        if not user_messages:
            continue

        gen_uuids_seen.append(event_uuid)

        for idx, msg_text in enumerate(user_messages):
            if len(pending) >= MAX_TOTAL_CLASSIFICATIONS:
                cap_hit = True
                break
            pending.append(
                _PendingClassification(
                    trace_id=input.trace_id,
                    gen_uuid=event_uuid,
                    msg_index=idx,
                    text=truncate_to_token_limit(msg_text),
                )
            )
        if cap_hit:
            logger.warning(
                "Hit classification cap for trace",
                trace_id=input.trace_id,
                cap=MAX_TOTAL_CLASSIFICATIONS,
                generations_seen=len(gen_uuids_seen),
            )
            break

    if not pending:
        return {
            "trace_id": input.trace_id,
            **_EMPTY_RESULT,
            "generations": {},
            "generation_count": 0,
            "message_count": 0,
        }

    # Phase 2: batch classify all collected texts at once
    results = classify_batch([p.text for p in pending])

    # Phase 3: reconstruct per-generation and per-message structures
    gen_messages: dict[str, list[dict[str, Any]]] = {}
    all_scores: list[dict[str, float]] = []

    for item, result in zip(pending, results):
        msg_dict = {
            "index": item.msg_index,
            "label": result.label,
            "score": result.score,
            "scores": result.scores,
        }
        gen_messages.setdefault(item.gen_uuid, []).append(msg_dict)
        all_scores.append(result.scores)

    generations: dict[str, Any] = {}
    for gen_uuid in gen_uuids_seen:
        msgs = gen_messages.get(gen_uuid)
        if not msgs:
            continue
        gen_scores = _average_scores(msgs)
        gen_label = max(gen_scores, key=gen_scores.get)  # type: ignore
        generations[gen_uuid] = {
            "label": gen_label,
            "score": gen_scores[gen_label],
            "scores": gen_scores,
            "messages": msgs,
        }

    # Trace-level: average across all messages
    trace_scores = _average_score_dicts(all_scores)
    trace_label = max(trace_scores, key=trace_scores.get)  # type: ignore

    return {
        "trace_id": input.trace_id,
        "label": trace_label,
        "score": round(trace_scores[trace_label], 4),
        "scores": trace_scores,
        "generations": generations,
        "generation_count": len(generations),
        "message_count": len(pending),
    }


def _average_scores(message_results: list[dict[str, Any]]) -> dict[str, float]:
    """Average softmax scores across message results."""
    score_dicts = [m["scores"] for m in message_results]
    return _average_score_dicts(score_dicts)


def _average_score_dicts(score_dicts: list[dict[str, float]]) -> dict[str, float]:
    """Average a list of {label: score} dicts."""
    if not score_dicts:
        return {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    labels = ["positive", "neutral", "negative"]
    n = len(score_dicts)
    return {label: round(sum(d.get(label, 0.0) for d in score_dicts) / n, 4) for label in labels}


def _build_trace_result(
    trace_id: str,
    pending: list[_PendingClassification],
    gen_uuids_seen: list[str],
    classification_results: list,
    pending_offset: int,
) -> tuple[dict[str, Any], int]:
    """Build a single trace's sentiment result from classified pending items.

    Returns (result_dict, count_consumed) where count_consumed is how many
    items from classification_results were used.
    """
    # Filter pending items for this trace
    trace_pending = [p for p in pending if p.trace_id == trace_id]
    trace_results = classification_results[pending_offset : pending_offset + len(trace_pending)]

    if not trace_pending:
        return {
            "trace_id": trace_id,
            **_EMPTY_RESULT,
            "generations": {},
            "generation_count": 0,
            "message_count": 0,
        }, 0

    gen_messages: dict[str, list[dict[str, Any]]] = {}
    all_scores: list[dict[str, float]] = []

    for item, result in zip(trace_pending, trace_results):
        msg_dict = {
            "index": item.msg_index,
            "label": result.label,
            "score": result.score,
            "scores": result.scores,
        }
        gen_messages.setdefault(item.gen_uuid, []).append(msg_dict)
        all_scores.append(result.scores)

    generations: dict[str, Any] = {}
    trace_gen_uuids = [u for u in gen_uuids_seen if u in gen_messages]
    for gen_uuid in trace_gen_uuids:
        msgs = gen_messages[gen_uuid]
        gen_scores = _average_scores(msgs)
        gen_label = max(gen_scores, key=gen_scores.get)  # type: ignore
        generations[gen_uuid] = {
            "label": gen_label,
            "score": gen_scores[gen_label],
            "scores": gen_scores,
            "messages": msgs,
        }

    trace_scores = _average_score_dicts(all_scores)
    trace_label = max(trace_scores, key=trace_scores.get)  # type: ignore

    return {
        "trace_id": trace_id,
        "label": trace_label,
        "score": round(trace_scores[trace_label], 4),
        "scores": trace_scores,
        "generations": generations,
        "generation_count": len(generations),
        "message_count": len(trace_pending),
    }, len(trace_pending)


@temporalio.activity.defn
async def classify_sentiment_batch_activity(input: OnDemandSentimentBatchInput) -> dict[str, dict[str, Any]]:
    """Fetch $ai_generation events for multiple traces in one query and classify sentiment."""
    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.models.team import Team
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_GENERATIONS, MAX_TOTAL_CLASSIFICATIONS
    from posthog.temporal.llm_analytics.sentiment.extraction import (
        extract_user_messages_individually,
        truncate_to_token_limit,
    )
    from posthog.temporal.llm_analytics.sentiment.model import classify_batch

    team = Team.objects.get(id=input.team_id)
    resolved_from, resolved_to = _resolve_date_bounds(input.date_from, input.date_to)

    query = parse_select(_GENERATIONS_BATCH_QUERY)
    result = execute_hogql_query(
        query_type="SentimentOnDemandBatch",
        query=query,
        placeholders={
            "date_from": ast.Constant(value=resolved_from),
            "date_to": ast.Constant(value=resolved_to),
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in input.trace_ids]),
        },
        team=team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    # Group rows by trace_id, enforcing per-trace generation limit
    rows_by_trace: dict[str, list[tuple]] = {}
    for row in result.results or []:
        row_trace_id = str(row[2])
        trace_rows = rows_by_trace.setdefault(row_trace_id, [])
        if len(trace_rows) < MAX_GENERATIONS:
            trace_rows.append(row)

    # Collect all texts to classify across all traces
    pending: list[_PendingClassification] = []
    gen_uuids_seen: list[str] = []
    per_trace_cap: dict[str, int] = {}

    for trace_id in input.trace_ids:
        trace_rows = rows_by_trace.get(trace_id, [])
        trace_count = 0

        for row in trace_rows:
            event_uuid = str(row[0])
            raw_props = row[1]
            props = json.loads(raw_props) if isinstance(raw_props, str) else raw_props

            user_messages = extract_user_messages_individually(props.get("$ai_input"))
            if not user_messages:
                continue

            gen_uuids_seen.append(event_uuid)

            for idx, msg_text in enumerate(user_messages):
                if trace_count >= MAX_TOTAL_CLASSIFICATIONS:
                    break
                pending.append(
                    _PendingClassification(
                        trace_id=trace_id,
                        gen_uuid=event_uuid,
                        msg_index=idx,
                        text=truncate_to_token_limit(msg_text),
                    )
                )
                trace_count += 1

        per_trace_cap[trace_id] = trace_count

    # Batch classify all texts across all traces in one call
    all_results = classify_batch([p.text for p in pending]) if pending else []

    # Build per-trace results
    output: dict[str, dict[str, Any]] = {}
    offset = 0
    for trace_id in input.trace_ids:
        trace_result, consumed = _build_trace_result(trace_id, pending, gen_uuids_seen, all_results, offset)
        output[trace_id] = trace_result
        offset += consumed

    return output


@temporalio.workflow.defn(name="llma-sentiment-on-demand-batch")
class OnDemandSentimentBatchWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> OnDemandSentimentBatchInput:
        return OnDemandSentimentBatchInput(
            team_id=int(inputs[0]),
            trace_ids=inputs[1:],
        )

    @temporalio.workflow.run
    async def run(self, input: OnDemandSentimentBatchInput) -> dict[str, dict[str, Any]]:
        return await temporalio.workflow.execute_activity(
            classify_sentiment_batch_activity,
            input,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@temporalio.workflow.defn(name="llma-sentiment-on-demand")
class OnDemandSentimentWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> OnDemandSentimentInput:
        return OnDemandSentimentInput(
            team_id=int(inputs[0]),
            trace_id=inputs[1],
        )

    @temporalio.workflow.run
    async def run(self, input: OnDemandSentimentInput) -> dict[str, Any]:
        return await temporalio.workflow.execute_activity(
            classify_sentiment_on_demand_activity,
            input,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
