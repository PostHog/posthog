from __future__ import annotations

import re
from uuid import UUID

from posthog.dataclasses import frozen

# Same contract as CreateGeneratedKnowledgeDocument.provider.
LEARNING_PROVIDER_NAME_MAX_LENGTH = 64
_LEARNING_PROVIDER_NAME_RE = re.compile(r"[a-z0-9_-]+")


def evidence_key_for(ticket_id: UUID, resolution_comment_id: UUID) -> str:
    return f"{ticket_id}:{resolution_comment_id}"


def validate_learning_provider_name(name: str) -> None:
    if not name or len(name) > LEARNING_PROVIDER_NAME_MAX_LENGTH or _LEARNING_PROVIDER_NAME_RE.fullmatch(name) is None:
        raise ValueError(f"learning provider name {name!r} is invalid")


@frozen
class EvidenceRef:
    evidence_key: str
    source_team_id: int
    display_label: str
    deep_link: str
    provider: str
    ticket_id: UUID
    ticket_number: int
    resolution_comment_id: UUID

    def __post_init__(self) -> None:
        validate_learning_provider_name(self.provider)
        if self.source_team_id <= 0:
            raise ValueError("source_team_id must be a positive team id")
        if self.ticket_number <= 0:
            raise ValueError("ticket_number must be positive")
        if not self.display_label:
            raise ValueError("display_label is required")
        if not self.deep_link:
            raise ValueError("deep_link is required")
        expected_key = evidence_key_for(self.ticket_id, self.resolution_comment_id)
        if self.evidence_key != expected_key:
            raise ValueError("evidence_key must be ticket_id:resolution_comment_id")


@frozen
class EvidenceBundle:
    replies: tuple[str, ...]
