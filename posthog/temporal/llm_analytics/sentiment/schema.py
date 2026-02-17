"""Dataclasses and constants for sentiment classification workflows."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ClassifySentimentInput:
    team_id: int
    trace_ids: list[str]
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class PendingClassification:
    trace_id: str
    gen_uuid: str
    msg_index: int
    text: str


_EMPTY_RESULT: dict[str, Any] = {
    "label": "neutral",
    "score": 0.0,
    "scores": {"positive": 0.0, "neutral": 0.0, "negative": 0.0},
}


def empty_trace_result(trace_id: str) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        **_EMPTY_RESULT,
        "generations": {},
        "generation_count": 0,
        "message_count": 0,
    }
