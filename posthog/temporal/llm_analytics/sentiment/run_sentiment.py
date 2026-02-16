"""Temporal workflow and activity for async sentiment classification of $ai_generation events.

Processes batches of events: the Kafka scheduler collects sampled events and starts
one workflow containing them all. The activity classifies each event independently,
emitting individual $ai_sentiment events. Individual failures are logged and skipped.
"""

import json
import uuid
import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
import temporalio
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.sentiment.constants import (
    ACTIVITY_HEARTBEAT_TIMEOUT,
    ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
    ACTIVITY_START_TO_CLOSE_TIMEOUT,
    LABELS,
    MODEL_NAME,
    RETRY_BACKOFF_COEFFICIENT,
    RETRY_INITIAL_INTERVAL,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_INTERVAL,
)
from posthog.temporal.llm_analytics.sentiment.extraction import (
    extract_user_messages_individually,
    truncate_to_token_limit,
)
from posthog.temporal.llm_analytics.sentiment.model import classify

logger = structlog.get_logger(__name__)

# Serializes classify() calls so only one thread runs the ONNX export at a time.
# torch.export is not thread-safe; concurrent exports corrupt global state.
_classify_lock = asyncio.Lock()

SENTIMENT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=RETRY_MAX_ATTEMPTS,
    initial_interval=RETRY_INITIAL_INTERVAL,
    maximum_interval=RETRY_MAX_INTERVAL,
    backoff_coefficient=RETRY_BACKOFF_COEFFICIENT,
)


@dataclass
class SentimentClassificationInput:
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "event_count": len(self.events),
            "event_uuids": [e.get("uuid") for e in self.events[:5]],
        }


@dataclass
class SentimentClassificationResult:
    label: str
    score: float
    scores: dict[str, float]
    text: str
    skipped: bool = False
    skip_reason: str | None = None


async def _classify_single_event(event_data: dict[str, Any]) -> dict[str, Any]:
    """Classify sentiment for a single $ai_generation event and emit $ai_sentiment.

    Returns a result dict with classification info or skip/error status.
    """
    team_id = event_data["team_id"]
    bind_contextvars(team_id=team_id, event_uuid=event_data.get("uuid"))

    properties = event_data.get("properties", {})
    if isinstance(properties, str):
        properties = json.loads(properties)

    ai_input = properties.get("$ai_input")
    if not ai_input:
        logger.info("Skipping sentiment: no $ai_input")
        return {
            "skipped": True,
            "skip_reason": "no_ai_input",
        }

    individual_messages = extract_user_messages_individually(ai_input)
    if not individual_messages:
        logger.info("Skipping sentiment: no user messages")
        return {
            "skipped": True,
            "skip_reason": "no_user_messages",
        }

    per_message_results: list[dict[str, Any]] = []
    classify_results: list[SentimentClassificationResult] = []
    for text in individual_messages:
        truncated = truncate_to_token_limit(text)
        msg_result = await asyncio.to_thread(classify, truncated)
        per_message_results.append(
            {
                "label": msg_result.label,
                "score": msg_result.score,
            }
        )
        classify_results.append(
            SentimentClassificationResult(
                label=msg_result.label,
                score=msg_result.score,
                scores=msg_result.scores,
                text=truncated,
            )
        )

    # Overall sentiment = average of per-message softmax scores
    n = len(classify_results)
    overall_scores = {label: sum(r.scores.get(label, 0.0) for r in classify_results) / n for label in LABELS}
    overall_label = max(overall_scores, key=overall_scores.__getitem__)
    overall_score = overall_scores[overall_label]

    # Max per-message scores, only from messages where that label won
    positive_max_score = max((r.score for r in classify_results if r.label == "positive"), default=0.0)
    negative_max_score = max((r.score for r in classify_results if r.label == "negative"), default=0.0)

    # Emit $ai_sentiment event
    trace_id = properties.get("$ai_trace_id")
    session_id = properties.get("$ai_session_id")
    generation_event_uuid = event_data.get("uuid")
    generation_parent_id = properties.get("$ai_generation_id") or properties.get("$ai_span_id") or generation_event_uuid
    distinct_id = event_data.get("distinct_id", "")
    generation_timestamp = event_data.get("timestamp")

    def _emit():
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=team_id)
            raise ValueError(f"Team {team_id} not found")

        sentiment_properties: dict[str, Any] = {
            "$ai_trace_id": trace_id,
            "$ai_session_id": session_id,
            "$ai_parent_id": generation_parent_id,
            "$ai_generation_event_uuid": generation_event_uuid,
            "$ai_sentiment_label": overall_label,
            "$ai_sentiment_score": overall_score,
            "$ai_sentiment_scores": overall_scores,
            "$ai_sentiment_positive_max_score": positive_max_score,
            "$ai_sentiment_negative_max_score": negative_max_score,
            "$ai_sentiment_model": MODEL_NAME,
            "$ai_sentiment_messages": per_message_results,
        }

        person_id = uuid.UUID(event_data["person_id"]) if event_data.get("person_id") else None

        create_event(
            event_uuid=uuid.uuid4(),
            event="$ai_sentiment",
            team=team,
            distinct_id=distinct_id,
            timestamp=generation_timestamp or datetime.now(UTC),
            properties=sentiment_properties,
            person_id=person_id,
        )

    await database_sync_to_async(_emit, thread_sensitive=False)()

    return {
        "skipped": False,
        "label": overall_label,
        "score": overall_score,
        "scores": overall_scores,
        "per_message": per_message_results,
    }


@temporalio.activity.defn
async def classify_sentiment_activity(input: SentimentClassificationInput) -> dict[str, Any]:
    """Classify sentiment for a batch of $ai_generation events.

    Processes each event independently with try/except so individual failures
    don't block the rest of the batch.
    """
    processed = 0
    skipped = 0
    failed = 0
    results: list[dict[str, Any]] = []

    async with _classify_lock:
        for i, event_data in enumerate(input.events):
            try:
                result = await _classify_single_event(event_data)
                if result.get("skipped"):
                    skipped += 1
                else:
                    processed += 1
                results.append(result)
            except Exception:
                logger.exception(
                    "Failed to classify event",
                    event_uuid=event_data.get("uuid"),
                    team_id=event_data.get("team_id"),
                )
                failed += 1
                results.append({"skipped": False, "error": True, "event_uuid": event_data.get("uuid")})

            temporalio.activity.heartbeat(f"event {i + 1}/{len(input.events)}")

    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "results": results,
    }


@temporalio.workflow.defn(name="llma-run-sentiment-classification")
class RunSentimentClassificationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SentimentClassificationInput:
        return SentimentClassificationInput(
            events=json.loads(inputs[0]),
        )

    @temporalio.workflow.run
    async def run(self, input: SentimentClassificationInput) -> dict[str, Any]:
        result = await temporalio.workflow.execute_activity(
            classify_sentiment_activity,
            input,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            schedule_to_close_timeout=ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT,
            heartbeat_timeout=ACTIVITY_HEARTBEAT_TIMEOUT,
            retry_policy=SENTIMENT_RETRY_POLICY,
        )
        return result
