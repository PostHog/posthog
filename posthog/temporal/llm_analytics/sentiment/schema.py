"""Dataclasses for sentiment classification workflows."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClassifySentimentInput:
    team_id: int
    trace_ids: list[str]
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
    trace_id: str
    label: str
    score: float
    scores: dict[str, float]
    generations: dict[str, Any] = field(default_factory=dict)
    generation_count: int = 0
    message_count: int = 0

    @classmethod
    def neutral(cls, trace_id: str) -> "TraceResult":
        return cls(
            trace_id=trace_id, label="neutral", score=0.0, scores={"positive": 0.0, "neutral": 0.0, "negative": 0.0}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "label": self.label,
            "score": self.score,
            "scores": self.scores,
            "generations": self.generations,
            "generation_count": self.generation_count,
            "message_count": self.message_count,
        }


@dataclass
class PendingClassification:
    trace_id: str
    gen_uuid: str
    msg_index: int
    text: str
