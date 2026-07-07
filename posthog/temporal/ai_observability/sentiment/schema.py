"""Dataclasses for sentiment evaluations."""

from dataclasses import dataclass


@dataclass
class SentimentResult:
    label: str
    score: float
    scores: dict[str, float]

    @classmethod
    def neutral(cls) -> "SentimentResult":
        return cls(label="neutral", score=0.0, scores={"positive": 0.0, "neutral": 0.0, "negative": 0.0})


@dataclass
class PendingClassification:
    trace_id: str
    gen_uuid: str
    msg_index: int
    text: str
