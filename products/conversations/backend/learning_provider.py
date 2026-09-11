from __future__ import annotations

from datetime import datetime

from products.business_knowledge.backend.learning.contracts import EvidenceBundle, EvidenceRef, evidence_key_for
from products.business_knowledge.backend.learning.providers import get_learning_provider, register_learning_provider
from products.business_knowledge.backend.models.constants import LearningProvider


class ConversationsLearningProvider:
    name: str = LearningProvider.CONVERSATIONS

    def collect(self, team_id: int, *, since: datetime, limit: int) -> list[EvidenceRef]:
        from products.conversations.backend.facade.api import (  # noqa: PLC0415 — keeps temporalio off the startup path
            list_resolved_ticket_revisions,
        )

        return [
            EvidenceRef(
                evidence_key=evidence_key_for(revision.ticket_id, revision.resolution_comment_id),
                source_team_id=revision.source_team_id,
                display_label=revision.display_label,
                deep_link=revision.deep_link,
                provider=self.name,
                ticket_id=revision.ticket_id,
                ticket_number=revision.ticket_number,
                resolution_comment_id=revision.resolution_comment_id,
            )
            for revision in list_resolved_ticket_revisions(team_id, since=since, limit=limit)
        ]

    def load(self, ref: EvidenceRef) -> EvidenceBundle | None:
        from products.conversations.backend.facade.api import (  # noqa: PLC0415 — keeps temporalio off the startup path
            get_public_human_replies,
        )

        replies = get_public_human_replies(
            ref.source_team_id,
            ref.ticket_id,
            resolution_comment_id=ref.resolution_comment_id,
        )
        if replies is None:
            return None
        return EvidenceBundle(replies=replies.replies)


def register_conversations_learning_provider() -> None:
    if get_learning_provider(LearningProvider.CONVERSATIONS) is not None:
        return
    register_learning_provider(ConversationsLearningProvider())
