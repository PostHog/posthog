from dataclasses import dataclass
from typing import Literal, get_args

import structlog
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from posthog.dataclasses import frozen

from products.business_knowledge.backend.learning.contracts import EvidenceRef

from .constants import LEARNING_DEFAULT_LOOKBACK_DAYS, LEARNING_MAX_ANSWER_CHARS, LEARNING_MAX_TOPIC_CHARS

RejectionCode = Literal[
    "none",
    "ineligible",
    "case_specific",
    "not_useful",
    "unsupported",
    "pii",
    "already_known",
    "low_confidence",
    "already_completed",
    "learned_cap_reached",
    "stale_candidate",
    "output_truncated",
]
LearningResult = Literal["knowledge_created", "no_knowledge", "ineligible", "superseded"]
ExtractionRejectionCode = Literal["none", "case_specific", "not_useful", "unsupported", "low_confidence"]
PromotionRejectionCode = Literal[
    "none",
    "case_specific",
    "not_useful",
    "unsupported",
    "already_known",
    "low_confidence",
    "stale_candidate",
]

logger = structlog.get_logger(__name__)


def _known_rejection_code(value: object, allowed: tuple[str, ...], stage: str) -> object:
    # Tool input does not enforce the schema enum, and temperature 0 returns the same invented code on every retry.
    # A rejection stops publication, so mapping an unknown code to one fails closed and lets the run complete.
    if value in allowed:
        return value
    logger.warning("business_knowledge.learning.unknown_rejection_code", stage=stage)
    return "not_useful"


@dataclass(frozen=True)
class AnalyzeLearningEvidenceInput:
    team_id: int
    run_id: str
    evidence: EvidenceRef


@dataclass(frozen=True)
class AnalyzeLearningEvidenceOutput:
    result: LearningResult
    knowledge_document_id: str | None
    rejection_code: RejectionCode


@dataclass(frozen=True)
class LearningCoordinatorInput:
    lookback_days: int = LEARNING_DEFAULT_LOOKBACK_DAYS
    team_id: int | None = None
    ticket_id: str | None = None


@dataclass(frozen=True)
class LearningWorkItem:
    team_id: int
    run_id: str
    evidence: EvidenceRef


@dataclass(frozen=True)
class CollectLearningEvidenceOutput:
    items: list[LearningWorkItem]


@dataclass(frozen=True)
class LearningCoordinatorOutput:
    eligible_count: int
    started_count: int
    skipped_count: int


class ExtractedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    canonical_topic: str = Field(min_length=1, max_length=LEARNING_MAX_TOPIC_CHARS)
    canonical_answer: str = Field(min_length=1, max_length=LEARNING_MAX_ANSWER_CHARS)
    generalizable: StrictBool
    useful: StrictBool
    supported_by_public_human_resolution: StrictBool
    confidence: float = Field(ge=0, le=1)
    rejection_code: ExtractionRejectionCode

    @field_validator("rejection_code", mode="before")
    @classmethod
    def _unknown_rejection_code_rejects(cls, value: object) -> object:
        return _known_rejection_code(value, get_args(ExtractionRejectionCode), "extraction")


class PiiVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["safe", "unsafe", "uncertain"]


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    generalizable: StrictBool
    useful: StrictBool
    supported_by_public_human_resolution: StrictBool
    missing_from_business_knowledge: StrictBool
    contradicts_existing: StrictBool = False
    conflicting_index: int | None = Field(default=None, ge=0)
    confidence: float = Field(ge=0, le=1)
    rejection_code: PromotionRejectionCode

    @field_validator("rejection_code", mode="before")
    @classmethod
    def _unknown_rejection_code_rejects(cls, value: object) -> object:
        return _known_rejection_code(value, get_args(PromotionRejectionCode), "promotion")


class ContradictionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    is_contradiction: StrictBool
    confidence: float = Field(ge=0, le=1)


@frozen
class LearningCandidate:
    canonical_topic: str
    canonical_answer: str
    generalizable: bool
    useful: bool
    supported_by_public_human_resolution: bool
    pii_free: bool
    missing_from_business_knowledge: bool
    confidence: float
    rejection_code: RejectionCode
