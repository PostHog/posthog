import json
import asyncio
from typing import Any

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.ai_observability.evaluation_event_io import extract_event_io
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.metrics import increment_sentiment_defaulted
from posthog.temporal.ai_observability.sentiment.constants import SENTIMENT_EVAL_REASONING_SNIPPET_CHARS
from posthog.temporal.ai_observability.sentiment.extraction import extract_sentiment_eval_messages
from posthog.temporal.ai_observability.sentiment.schema import PendingClassification, SentimentResult
from posthog.temporal.ai_observability.sentiment.utils import build_generation_result


def _neutral_sentiment_activity_result(reasoning: str) -> EvaluationActivityResult:
    return {
        "result_type": "sentiment",
        "reasoning": reasoning,
        "sentiment_label": "neutral",
        "sentiment_score": 0.0,
        "sentiment_scores": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
        "sentiment_messages": {},
        "sentiment_message_count": 0,
        "sentiment_defaulted": True,
    }


def _reasoning_snippet(text: str) -> str:
    """Collapse whitespace and bound a classified message for the reasoning string.

    Echoing the classified text lets a reviewer audit a sentiment label without pulling the
    source trace.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= SENTIMENT_EVAL_REASONING_SNIPPET_CHARS:
        return collapsed
    return collapsed[:SENTIMENT_EVAL_REASONING_SNIPPET_CHARS].rstrip() + "…"


def _build_sentiment_activity_result(
    event_uuid: str,
    trace_id: str,
    user_messages: list[tuple[int, str]],
    classification_results: list[SentimentResult],
) -> EvaluationActivityResult:
    if not user_messages:
        return _neutral_sentiment_activity_result("No user messages found; sentiment defaults to neutral.")
    if not classification_results:
        return _neutral_sentiment_activity_result(
            "No sentiment classifications produced; sentiment defaults to neutral."
        )

    pending = [
        PendingClassification(
            trace_id=trace_id,
            gen_uuid=event_uuid,
            msg_index=message_index,
            text=text,
        )
        for message_index, text in user_messages
    ]
    generation_result = build_generation_result(event_uuid, pending, classification_results)
    label = generation_result["label"]
    message_count = generation_result["message_count"]

    plural = "s" if message_count != 1 else ""
    snippet = _reasoning_snippet(user_messages[-1][1])
    reasoning = f"Classified {message_count} user message{plural} as {label}"
    reasoning = f'{reasoning}: "{snippet}"' if snippet else f"{reasoning}."

    return {
        "result_type": "sentiment",
        "reasoning": reasoning,
        "sentiment_label": label,
        "sentiment_score": generation_result["score"],
        "sentiment_scores": generation_result["scores"],
        "sentiment_messages": generation_result["messages"],
        "sentiment_message_count": message_count,
        "sentiment_defaulted": False,
    }


@activity.defn
async def execute_sentiment_eval_activity(
    evaluation: dict[str, Any], event_data: dict[str, Any]
) -> EvaluationActivityResult:
    """Classify sentiment for the target event's user messages."""
    if evaluation["evaluation_type"] != "sentiment":
        raise ApplicationError(
            f"Unsupported evaluation type: {evaluation['evaluation_type']}",
            non_retryable=True,
        )

    output_type = evaluation["output_type"]
    if output_type != "sentiment":
        raise ApplicationError(
            f"Unsupported output type: {output_type}. Supported types: 'sentiment'.",
            non_retryable=True,
        )

    evaluation_config = evaluation.get("evaluation_config", {})
    source = evaluation_config.get("source", "user_messages")
    if source != "user_messages":
        raise ApplicationError(
            f"Unsupported sentiment source: {source}. Supported sources: 'user_messages'.",
            non_retryable=True,
        )

    properties = event_data["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    input_raw, _output_raw = extract_event_io(event_data["event"], properties)
    event_uuid = event_data["uuid"]
    trace_id = properties.get("$ai_trace_id", event_uuid)
    user_messages = extract_sentiment_eval_messages(input_raw)
    if not user_messages:
        increment_sentiment_defaulted("no_user_messages")
        return _neutral_sentiment_activity_result("No user messages found; sentiment defaults to neutral.")

    texts = [text for _message_index, text in user_messages]

    from posthog.temporal.ai_observability.sentiment.model import classify  # noqa: PLC0415 -- loads ONNX deps lazily

    classification_results = await asyncio.to_thread(classify, texts)
    result = _build_sentiment_activity_result(event_uuid, trace_id, user_messages, classification_results)
    if result.get("sentiment_defaulted"):
        increment_sentiment_defaulted("no_classifications")
    return result
