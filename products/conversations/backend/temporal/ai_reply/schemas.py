"""Activity and workflow I/O types for the support-reply Temporal pipeline.

Dataclasses define inputs/outputs passed across activity boundaries (and into
SupportReplyWorkflow). Pydantic models (SupportReplyDraft, SupportReplySource) are
structured LLM response schemas used by the draft sandbox step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


@dataclass
class SupportReplyInput:
    team_id: int
    ticket_id: str


@dataclass
class BuildContextOutput:
    ticket_context: str
    ticket_title: str
    always_on_context: str = ""
    # Team opted into letting the agent investigate the customer's own data (wider read scopes
    # on diagnostic tickets). Off by default: a crafted ticket can't unlock those scopes alone.
    diagnostics_allowed: bool = False


@dataclass
class ClassifyInput:
    team_id: int
    ticket_context: str


@dataclass
class ClassifyOutput:
    ticket_type: str
    needs_diagnostics: bool
    seed_queries: list[str] = field(default_factory=list)


@dataclass
class RefineQueriesInput:
    team_id: int
    ticket_context: str
    missing: list[str] = field(default_factory=list)
    ticket_type: str = "how_to"
    seed_queries: list[str] = field(default_factory=list)


@dataclass
class RefineQueriesOutput:
    queries: list[str]


@dataclass
class RetrieveInput:
    team_id: int
    queries: list[str]
    prior_citation_chunk_ids: list[str] = field(default_factory=list)
    widen: bool = False


@dataclass
class RetrieveOutput:
    # Only chunk ids cross the activity boundary — content is rehydrated from the DB
    # (deterministic) where it's needed, to keep workflow history small.
    chunk_ids: list[str]


@dataclass
class DraftInput:
    team_id: int
    ticket_context: str
    chunk_ids: list[str]
    # Refinement feedback from the previous attempt so the agent improves a good draft
    # instead of re-rolling blind (which tends to drift to a worse, less-grounded answer).
    prior_reply: str = ""
    prior_missing: list[str] = field(default_factory=list)
    always_on_context: str = ""
    ticket_type: str = "how_to"
    # Classifier hint: the ticket needs data investigation. Gates the diagnostic prompt block.
    needs_diagnostics: bool = False
    # Org opt-in (ai_diagnostics_enabled): gates the read_only scope preset independently
    # of the classifier. When True the agent gets full reads on every ticket.
    diagnostics_allowed: bool = False


@dataclass
class DraftOutput:
    reply: str
    citations: list[str]
    confidence: float
    # Evidence the agent actually relied on (BK chunk or doc URL + supporting excerpt).
    # Lets validation ground against sources gathered via MCP tools, not just seed chunks.
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ValidateInput:
    team_id: int
    ticket_context: str
    reply: str
    citations: list[str]
    chunk_ids: list[str]
    sources: list[dict[str, str]] = field(default_factory=list)
    ticket_type: str = "how_to"


@dataclass
class ValidateOutput:
    grounded: bool
    coverage: float
    confidence: float
    missing: list[str]


@dataclass
class PersistReplyInput:
    team_id: int
    ticket_id: str
    reply: str
    citations: list[str]
    confidence: float
    ticket_type: str = "how_to"
    allow_bot_reply: bool = False


@dataclass
class RecordTriageInput:
    team_id: int
    ticket_id: str
    patch: dict[str, Any]


@dataclass
class SafetyFilterInput:
    team_id: int
    ticket_context: str


@dataclass
class SafetyFilterOutput:
    safe: bool
    threat_type: str = ""
    explanation: str = ""


@dataclass
class ReviewReplyInput:
    team_id: int
    ticket_context: str
    reply: str
    sources: list[dict[str, str]] = field(default_factory=list)
    ticket_type: str = "how_to"


@dataclass
class ReviewReplyOutput:
    safe: bool
    reason: str = ""


@dataclass
class PersistKnowledgeGapInput:
    team_id: int
    ticket_id: str
    missing: list[str] = field(default_factory=list)
    ticket_type: str = ""
    outcome: str = ""


class SupportReplySource(BaseModel):
    ref: str = Field(description="The citation reference: a chunk_id UUID or a documentation URL")
    excerpt: str = Field(description="The exact text from this source that supports the reply")


class SupportReplyDraft(BaseModel):
    reply: str = Field(description="The drafted reply text")
    citations: list[str] = Field(description="List of chunk_id UUIDs or doc URLs cited in the reply")
    confidence: float = Field(description="Confidence score 0-1 that the reply is correct and grounded")
    sources: list[SupportReplySource] = Field(
        default_factory=list,
        description="Every source used, each with the exact supporting excerpt, so the reply can be validated",
    )
