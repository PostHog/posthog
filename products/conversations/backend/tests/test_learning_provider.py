from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import SimpleTestCase
from django.utils import timezone

from posthog.models import Team
from posthog.models.comment import Comment

from products.business_knowledge.backend.learning import providers as providers_mod
from products.business_knowledge.backend.learning.contracts import evidence_key_for
from products.business_knowledge.backend.learning.providers import get_learning_provider, get_learning_providers
from products.conversations.backend.learning_provider import (
    ConversationsLearningProvider,
    register_conversations_learning_provider,
)
from products.conversations.backend.models.constants import Status
from products.conversations.backend.models.ticket import Ticket


class TestConversationsLearningProviderRegistration(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._saved = providers_mod._providers.copy()
        providers_mod._providers.clear()

    def tearDown(self) -> None:
        providers_mod._providers.clear()
        providers_mod._providers.update(self._saved)
        super().tearDown()

    def test_ready_can_register_twice_without_raising(self) -> None:
        register_conversations_learning_provider()
        register_conversations_learning_provider()

        provider = get_learning_provider("conversations")
        assert provider is not None
        assert provider.name == "conversations"
        assert len(get_learning_providers()) == 1


class TestConversationsLearningProvider(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save(update_fields=["conversations_enabled"])
        self.provider = ConversationsLearningProvider()
        self.since = timezone.now() - timedelta(days=7)

    def _ticket(self, *, team: Team | None = None, number: int = 1) -> Ticket:
        team = team or self.team
        return Ticket.objects.create(
            team=team,
            ticket_number=number,
            widget_session_id=f"learn-{number}-{team.id}",
            distinct_id=f"learn-d{number}-{team.id}",
            status=Status.RESOLVED,
        )

    def _support_reply(self, ticket: Ticket, content: str) -> Comment:
        return Comment.objects.create(
            team=ticket.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content=content,
            item_context={"author_type": "support", "is_private": False, "author_email": "agent@example.com"},
        )

    def test_collect_maps_the_latest_public_human_comment_to_an_evidence_ref(self) -> None:
        ticket = self._ticket()
        comment = self._support_reply(ticket, "The limit is 1000")

        refs = self.provider.collect(self.team.id, since=self.since, limit=10)
        bundle = self.provider.load(refs[0])

        assert len(refs) == 1
        assert refs[0].provider == "conversations"
        assert refs[0].ticket_id == ticket.id
        assert refs[0].ticket_number == 1
        assert refs[0].source_team_id == self.team.id
        assert refs[0].resolution_comment_id == comment.id
        assert refs[0].evidence_key == evidence_key_for(ticket.id, comment.id)
        assert bundle is not None
        assert bundle.replies == ("The limit is 1000",)

    def test_load_pins_replies_to_the_collected_revision(self) -> None:
        ticket = self._ticket()
        first = self._support_reply(ticket, "The limit is 1000")

        refs = self.provider.collect(self.team.id, since=self.since, limit=10)
        self._support_reply(ticket, "Also the burst is 5000")
        bundle = self.provider.load(refs[0])
        later_refs = self.provider.collect(self.team.id, since=self.since, limit=10)

        assert bundle is not None
        assert bundle.replies == ("The limit is 1000",)
        assert later_refs[0].resolution_comment_id != first.id
        later_bundle = self.provider.load(later_refs[0])
        assert later_bundle is not None
        assert later_bundle.replies == ("The limit is 1000", "Also the burst is 5000")

    def test_load_rejects_a_resolution_comment_that_is_no_longer_public(self) -> None:
        ticket = self._ticket()
        comment = self._support_reply(ticket, "The limit is 1000")

        refs = self.provider.collect(self.team.id, since=self.since, limit=10)
        Comment.objects.filter(pk=comment.id).update(deleted=True)

        assert self.provider.load(refs[0]) is None

    def test_child_environment_keeps_source_team_id_on_the_child(self) -> None:
        child = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
            conversations_enabled=True,
        )
        ticket = self._ticket(team=child)
        comment = self._support_reply(ticket, "Child environment answer")

        refs = self.provider.collect(child.id, since=self.since, limit=10)
        bundle = self.provider.load(refs[0])

        assert [ref.source_team_id for ref in refs] == [child.id]
        assert refs[0].evidence_key == evidence_key_for(ticket.id, comment.id)
        assert self.provider.collect(self.team.id, since=self.since, limit=10) == []
        assert bundle is not None
        assert bundle.replies == ("Child environment answer",)
