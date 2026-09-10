from uuid import UUID

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class CreateGeneratedKnowledgeDocument:
    team_id: int
    ticket_id: UUID
    resolution_comment_id: UUID
    analysis_version: str
    title: str
    content: str


@dataclass(frozen=True)
class GeneratedKnowledgeDocument:
    id: UUID
    source_id: UUID
    created: bool
