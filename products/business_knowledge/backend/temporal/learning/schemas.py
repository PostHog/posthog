from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from posthog.dataclasses import frozen

from products.business_knowledge.backend.learning.contracts import EvidenceRef

from .constants import LEARNING_MAX_ANSWER_CHARS, LEARNING_MAX_TOPIC_CHARS

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
]
LearningResult = Literal["knowledge_created", "no_knowledge", "ineligible"]
ExtractionRejectionCode = Literal["none", "case_specific", "not_useful", "unsupported", "low_confidence"]
PromotionRejectionCode = Literal[
    "none",
    "case_specific",
    "not_useful",
    "unsupported",
    "already_known",
    "low_confidence",
]


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


class ExtractedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)

    canonical_topic: str = Field(min_length=1, max_length=LEARNING_MAX_TOPIC_CHARS)
    canonical_answer: str = Field(min_length=1, max_length=LEARNING_MAX_ANSWER_CHARS)
    generalizable: StrictBool
    useful: StrictBool
    supported_by_public_human_resolution: StrictBool
    confidence: float = Field(ge=0, le=1)
    rejection_code: ExtractionRejectionCode


class PiiVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["safe", "unsafe", "uncertain"]


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    generalizable: StrictBool
    useful: StrictBool
    supported_by_public_human_resolution: StrictBool
    missing_from_business_knowledge: StrictBool
    confidence: float = Field(ge=0, le=1)
    rejection_code: PromotionRejectionCode


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
