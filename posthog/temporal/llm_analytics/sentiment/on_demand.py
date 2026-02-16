"""On-demand sentiment classification workflow.

Computes sentiment for a single trace and returns the result directly
(does NOT emit events). Used by the trace detail view to show sentiment
on-the-fly.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
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


@temporalio.activity.defn
async def classify_sentiment_on_demand_activity(input: OnDemandSentimentInput) -> dict[str, Any]:
    """Fetch $ai_generation events for a trace and classify sentiment on each user message."""
    from posthog.clickhouse.client import query_with_columns
    from posthog.temporal.llm_analytics.sentiment.extraction import (
        extract_user_messages_individually,
        truncate_to_token_limit,
    )
    from posthog.temporal.llm_analytics.sentiment.model import classify

    # Fetch all $ai_generation events for this trace
    query_result = query_with_columns(
        """
        SELECT
            uuid,
            properties
        FROM events
        WHERE team_id = %(team_id)s
          AND event = '$ai_generation'
          AND JSONExtractString(properties, '$ai_trace_id') = %(trace_id)s
        ORDER BY timestamp ASC
        LIMIT 100
        """,
        {"team_id": input.team_id, "trace_id": input.trace_id},
        team_id=input.team_id,
    )

    if not query_result:
        return {
            "trace_id": input.trace_id,
            "label": "neutral",
            "score": 0.0,
            "scores": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
            "generations": {},
            "generation_count": 0,
            "message_count": 0,
        }

    generations: dict[str, Any] = {}
    all_scores: list[dict[str, float]] = []
    total_messages = 0

    for row in query_result:
        event_uuid = str(row["uuid"])
        props = row["properties"]
        if isinstance(props, str):
            props = json.loads(props)

        ai_input = props.get("$ai_input")
        user_messages = extract_user_messages_individually(ai_input)

        if not user_messages:
            continue

        message_results = []
        for idx, msg_text in enumerate(user_messages):
            truncated = truncate_to_token_limit(msg_text)
            result = classify(truncated)
            message_results.append(
                {
                    "index": idx,
                    "label": result.label,
                    "score": result.score,
                    "scores": result.scores,
                }
            )
            all_scores.append(result.scores)

        total_messages += len(message_results)

        # Generation-level: average across its messages
        gen_scores = _average_scores(message_results)
        gen_label = max(gen_scores, key=gen_scores.get)  # type: ignore
        generations[event_uuid] = {
            "label": gen_label,
            "score": gen_scores[gen_label],
            "scores": gen_scores,
            "messages": message_results,
        }

    # Trace-level: average across all messages
    if all_scores:
        trace_scores = _average_score_dicts(all_scores)
        trace_label = max(trace_scores, key=trace_scores.get)  # type: ignore
        trace_score = trace_scores[trace_label]
    else:
        trace_label = "neutral"
        trace_score = 0.0
        trace_scores = {"positive": 0.0, "neutral": 0.0, "negative": 0.0}

    return {
        "trace_id": input.trace_id,
        "label": trace_label,
        "score": round(trace_score, 4),
        "scores": trace_scores,
        "generations": generations,
        "generation_count": len(generations),
        "message_count": total_messages,
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
