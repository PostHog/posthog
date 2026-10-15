from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models.comment import Comment

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.models import KnowledgeChunk
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status


class TestAiHumanOutcomeAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="ai-outcome-session",
            distinct_id="user-123",
            status=Status.OPEN,
            ai_triage={"status": "done", "result": "suggested"},
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/ai_human_outcome/"
        self.draft = self._create_ai_draft("Current draft")

    def _create_ai_draft(self, content: str) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context={"author_type": "AI", "is_private": True},
        )

    def _payload(self, outcome: str) -> dict[str, str]:
        return {"message_id": str(self.draft.id), "outcome": outcome}

    def test_records_used(self) -> None:
        response = self.client.post(self.url, self._payload("used"), format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json()["outcome"] == "used"
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_upgrades_used_to_edited(self) -> None:
        self.client.post(self.url, self._payload("used"), format="json")

        response = self.client.post(self.url, self._payload("edited"), format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "edited"

    def test_used_is_idempotent(self) -> None:
        self.client.post(self.url, self._payload("used"), format="json")

        response = self.client.post(self.url, self._payload("used"), format="json")

        assert response.status_code == status.HTTP_202_ACCEPTED
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "used"

    def test_rejects_a_second_non_upgrade_write(self) -> None:
        self.client.post(self.url, self._payload("edited"), format="json")

        response = self.client.post(self.url, self._payload("used"), format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error_type"] == "ai_draft_outcome_conflict"
        self.ticket.refresh_from_db()
        assert self.ticket.ai_triage["human_outcome"] == "edited"

    def test_rejects_ignored(self) -> None:
        response = self.client.post(self.url, self._payload("ignored"), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.ticket.refresh_from_db()
        assert "human_outcome" not in self.ticket.ai_triage

    def test_rejects_an_outcome_for_an_old_draft(self) -> None:
        self._create_ai_draft("Newer draft")

        response = self.client.post(self.url, self._payload("used"), format="json")

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error_type"] == "ai_draft_outcome_conflict"
        self.ticket.refresh_from_db()
        assert "human_outcome" not in self.ticket.ai_triage


class TestAiTriageSourcesAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="ai-sources-session",
            distinct_id="user-123",
            status=Status.OPEN,
        )
        self.text_source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Manual notes",
            text="Install the SDK from Project settings.",
        )
        self.chunk_id = str(
            KnowledgeChunk.objects.unscoped().filter(source_id=self.text_source.id).values_list("id", flat=True)[0]
        )

    def test_retrieve_hydrates_sources_from_triage_citations(self) -> None:
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "done", "result": "suggested", "citations": [self.chunk_id]}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        sources = response.json()["ai_triage"]["sources"]
        assert len(sources) == 1
        assert sources[0]["source_id"] == str(self.text_source.id)
        assert sources[0]["is_generated"] is False

    def test_list_does_not_hydrate_sources(self) -> None:
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "done", "result": "suggested", "citations": [self.chunk_id]}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/")

        assert response.status_code == status.HTTP_200_OK
        triage = response.json()["results"][0]["ai_triage"]
        assert "sources" not in triage
        assert triage["citations"] == [self.chunk_id]

    def _ai_comment(self, deleted: bool = False) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Suggested reply",
            deleted=deleted,
            item_context={
                "author_type": "AI",
                "is_private": True,
                "citations": [self.chunk_id],
            },
        )

    def test_empty_stored_citations_do_not_fall_back_to_an_older_comment(self) -> None:
        self._ai_comment()
        Ticket.objects.filter(id=self.ticket.id).update(
            ai_triage={"status": "done", "result": "suggested", "citations": []}
        )

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert "sources" not in response.json()["ai_triage"]

    def test_deleted_ai_comment_is_not_a_citation_fallback(self) -> None:
        self._ai_comment(deleted=True)
        Ticket.objects.filter(id=self.ticket.id).update(ai_triage={"status": "done", "result": "suggested"})

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert "sources" not in response.json()["ai_triage"]

    def test_retrieve_falls_back_to_latest_ai_comment_citations(self) -> None:
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Suggested reply",
            item_context={
                "author_type": "AI",
                "is_private": True,
                "citations": [self.chunk_id],
            },
        )
        Ticket.objects.filter(id=self.ticket.id).update(ai_triage={"status": "done", "result": "suggested"})

        response = self.client.get(f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/")

        assert response.status_code == status.HTTP_200_OK
        sources = response.json()["ai_triage"]["sources"]
        assert sources[0]["ref"] == self.chunk_id
