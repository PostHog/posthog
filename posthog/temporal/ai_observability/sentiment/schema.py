"""Dataclasses for sentiment classification workflows."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClassifySentimentInput:
    team_id: int
    ids: list[str]  # trace IDs or generation UUIDs depending on analysis_level
    analysis_level: str = "trace"  # "trace" or "generation"
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class SentimentResult:
    label: str
    score: float
    scores: dict[str, float]

    @classmethod
    def neutral(cls) -> "SentimentResult":
        return cls(label="neutral", score=0.0, scores={"positive": 0.0, "neutral": 0.0, "negative": 0.0})


@dataclass
class TraceResult:
    label: str
    score: float
    scores: dict[str, float]
    messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    message_count: int = 0

    @classmethod
    def neutral(cls) -> "TraceResult":
        return cls(label="neutral", score=0.0, scores={"positive": 0.0, "neutral": 0.0, "negative": 0.0})

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score": self.score,
            "scores": self.scores,
            "messages": self.messages,
            "message_count": self.message_count,
        }


@dataclass
class PendingClassification:
    trace_id: str
    gen_uuid: str
    msg_index: int
    text: str
