import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class CheckWatchedQuestionInputs:
    tracked_question_id: str
    team_id: int


@dataclass
class RetrievedTrackedQuestion:
    tracked_question_id: str
    team_id: int


@dataclass
class ForkConversationActivityInputs:
    tracked_question_id: str


@dataclass
class ForkConversationActivityResult:
    forked_conversation_id: str
    narrative: str
    query_kind: str


@dataclass
class JudgeDriftActivityInputs:
    tracked_question_id: str
    forked_conversation_id: str
    narrative: str


@dataclass
class JudgeDriftActivityResult:
    drift_detected: bool
    severity: Literal["none", "minor", "moderate", "significant"]
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmitDriftSignalActivityInputs:
    tracked_question_id: str
    forked_conversation_id: str
    narrative: str
    query_kind: str
    severity: Literal["minor", "moderate", "significant"]
    judge_summary: str


@dataclass
class EmitDriftSignalActivityResult:
    signal_emitted_at: dt.datetime | None
    signal_source_id: str


@dataclass
class PersistRunActivityInputs:
    tracked_question_id: str
    state: Literal["ok", "drifted", "error", "skipped"]
    severity: Literal["none", "minor", "moderate", "significant"] = "none"
    forked_conversation_id: str | None = None
    narrative: str = ""
    judge_summary: str = ""
    judge_payload: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    signal_emitted_at: dt.datetime | None = None
    signal_source_id: str = ""
