"""Temporal workflow and activity for async sentiment classification of $ai_generation events.

Follows the pattern of run_evaluation.py: a workflow that orchestrates activities
to fetch event data, classify sentiment, and emit a $ai_sentiment event.
"""

import json
import uuid
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
import temporalio
from structlog.contextvars import bind_contextvars
from temporalio.common import RetryPolicy

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.llm_analytics.sentiment.extraction import extract_user_messages, truncate_to_token_limit
from posthog.temporal.llm_analytics.sentiment.model import MODEL_NAME, classify

logger = structlog.get_logger(__name__)

# Serializes classify() calls so only one thread runs the ONNX export at a time.
# torch.export is not thread-safe; concurrent exports corrupt global state.
_classify_lock = asyncio.Lock()

SENTIMENT_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
)


@dataclass
class SentimentClassificationInput:
    event_data: dict[str, Any]

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.event_data.get("team_id"),
            "event_uuid": self.event_data.get("uuid"),
        }


@dataclass
class SentimentClassificationResult:
    label: str
    score: float
    scores: dict[str, float]
    text: str
    skipped: bool = False
    skip_reason: str | None = None


@temporalio.activity.defn
async def classify_sentiment_activity(input: SentimentClassificationInput) -> dict[str, Any]:
    """Classify sentiment of user messages in a $ai_generation event.

    1. Extract $ai_input from event properties
    2. Filter for user messages and concatenate
    3. Classify via local HuggingFace model
    4. Emit $ai_sentiment event to ClickHouse
    """
    event_data = input.event_data
    team_id = event_data["team_id"]
    bind_contextvars(team_id=team_id, event_uuid=event_data.get("uuid"))

    properties = event_data.get("properties", {})
    if isinstance(properties, str):
        properties = json.loads(properties)

    # Extract user messages from $ai_input
    ai_input = properties.get("$ai_input")
    if not ai_input:
        logger.info("Skipping sentiment: no $ai_input")
        return {
            "skipped": True,
            "skip_reason": "no_ai_input",
        }

    user_text = extract_user_messages(ai_input)
    if not user_text.strip():
        logger.info("Skipping sentiment: no user messages")
        return {
            "skipped": True,
            "skip_reason": "no_user_messages",
        }

    # Truncate to model limit
    truncated_text = truncate_to_token_limit(user_text)

    # Classify (run in thread to avoid blocking the Temporal event loop).
    # The async lock ensures only one coroutine loads the model at a time,
    # preventing concurrent torch ONNX exports which are not thread-safe.
    async with _classify_lock:
        result = await asyncio.to_thread(classify, truncated_text)

    # Emit $ai_sentiment event
    trace_id = properties.get("$ai_trace_id")
    generation_event_uuid = event_data.get("uuid")
    # Use the generation's logical ID so the sentiment event can nest under it
    # in the trace tree. The frontend resolves $ai_parent_id against
    # $ai_generation_id ?? $ai_span_id ?? event.id.
    generation_parent_id = properties.get("$ai_generation_id") or properties.get("$ai_span_id") or generation_event_uuid
    distinct_id = event_data.get("distinct_id", "")

    def _emit():
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=team_id)
            raise ValueError(f"Team {team_id} not found")

        sentiment_properties: dict[str, Any] = {
            "$ai_trace_id": trace_id,
            "$ai_parent_id": generation_parent_id,
            "$ai_generation_event_uuid": generation_event_uuid,
            "$ai_sentiment_label": result.label,
            "$ai_sentiment_score": result.score,
            "$ai_sentiment_scores": result.scores,
            "$ai_sentiment_text": truncated_text,
            "$ai_sentiment_model": MODEL_NAME,
        }

        person_id = uuid.UUID(event_data["person_id"]) if event_data.get("person_id") else None

        create_event(
            event_uuid=uuid.uuid4(),
            event="$ai_sentiment",
            team=team,
            distinct_id=distinct_id,
            timestamp=datetime.now(UTC),
            properties=sentiment_properties,
            person_id=person_id,
        )

    await database_sync_to_async(_emit, thread_sensitive=False)()

    return {
        "skipped": False,
        "label": result.label,
        "score": result.score,
        "scores": result.scores,
    }


@temporalio.workflow.defn(name="llma-run-sentiment-classification")
class RunSentimentClassificationWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SentimentClassificationInput:
        return SentimentClassificationInput(
            event_data=json.loads(inputs[0]),
        )

    @temporalio.workflow.run
    async def run(self, input: SentimentClassificationInput) -> dict[str, Any]:
        result = await temporalio.workflow.execute_activity(
            classify_sentiment_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=SENTIMENT_RETRY_POLICY,
        )
        return result
