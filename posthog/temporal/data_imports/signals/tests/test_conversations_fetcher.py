import uuid
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment
from posthog.temporal.data_imports.signals.conversations_tickets import CONVERSATIONS_TICKETS_CONFIG
from posthog.temporal.data_imports.signals.fetchers.conversations import conversations_ticket_fetcher

from products.conversations.backend.models import Ticket
from products.signals.backend.models import SignalEmissionRecord


def _make_ticket(team, **kwargs):
    return Ticket.objects.create_with_number(
        team=team,
        widget_session_id=str(uuid.uuid4()),
        distinct_id="user-123",
        channel_source="widget",
        **kwargs,
    )


def _backdate_ticket(ticket, hours=2):
    Ticket.objects.filter(id=ticket.id).update(created_at=timezone.now() - timedelta(hours=hours))


def _add_comment(team, ticket, content="Hello", author_type="customer", deleted=False):
    return Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=content,
        item_context={"author_type": author_type},
        deleted=deleted,
    )


@pytest.mark.django_db
class TestConversationsTicketFetcherEligibility(BaseTest):
    def test_returns_eligible_ticket(self):
        ticket = _make_ticket(self.team)
        _backdate_ticket(ticket, hours=2)

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert len(result) == 1
        assert result[0]["id"] == ticket.id

    def test_already_emitted_ticket_not_fetched_again(self):
        ticket = _make_ticket(self.team)
        _backdate_ticket(ticket, hours=2)

        first = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})
        assert len(first) == 1

        second = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})
        assert second == []


@pytest.mark.django_db
class TestConversationsTicketFetcherMessages(BaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = _make_ticket(self.team)
        _backdate_ticket(self.ticket, hours=2)

    def test_attaches_messages_to_ticket(self):
        _add_comment(self.team, self.ticket, content="Hello there", author_type="customer")

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert len(result) == 1
        messages = result[0]["messages"]
        assert len(messages) == 1
        assert messages[0] == ("customer", "Hello there")

    def test_attaches_multiple_messages_across_author_types(self):
        _add_comment(self.team, self.ticket, content="User question", author_type="customer")
        _add_comment(self.team, self.ticket, content="Team reply", author_type="team")

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert ("customer", "User question") in messages
        assert ("team", "Team reply") in messages

    def test_skips_empty_content_comments(self):
        _add_comment(self.team, self.ticket, content="Real message", author_type="customer")
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="",
            item_context={"author_type": "customer"},
        )

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert len(messages) == 1
        assert messages[0][1] == "Real message"

    def test_skips_none_content_comments(self):
        _add_comment(self.team, self.ticket, content="Real message", author_type="customer")
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=None,
            item_context={"author_type": "customer"},
        )

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert len(messages) == 1
        assert messages[0][1] == "Real message"

    def test_ticket_with_no_comments_gets_empty_messages(self):
        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert len(result) == 1
        assert result[0]["messages"] == []

    def test_comments_isolated_by_ticket(self):
        other_ticket = _make_ticket(self.team)
        _backdate_ticket(other_ticket, hours=2)

        _add_comment(self.team, self.ticket, content="Message for ticket one", author_type="customer")
        _add_comment(self.team, other_ticket, content="Message for ticket two", author_type="team")

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        by_id = {r["id"]: r["messages"] for r in result}
        assert by_id[self.ticket.id] == [("customer", "Message for ticket one")]
        assert by_id[other_ticket.id] == [("team", "Message for ticket two")]


@pytest.mark.django_db
class TestConversationsTicketFetcherAuthorType(BaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = _make_ticket(self.team)
        _backdate_ticket(self.ticket, hours=2)

    @parameterized.expand(
        [
            ("none_context", None),
            ("empty_context", {}),
            ("missing_author_type_key", {"other_key": "value"}),
        ]
    )
    def test_defaults_author_type_to_customer(self, _name, item_context):
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Some message",
            item_context=item_context,
        )

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert messages[0][0] == "customer"

    def test_preserves_team_author_type(self):
        _add_comment(self.team, self.ticket, content="Team message", author_type="team")

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert messages[0][0] == "team"

    def test_preserves_ai_author_type(self):
        _add_comment(self.team, self.ticket, content="AI message", author_type="AI")

        result = conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        messages = result[0]["messages"]
        assert messages[0][0] == "AI"


@pytest.mark.django_db
class TestConversationsTicketFetcherMarkEmitted(BaseTest):
    def _has_emission(self, ticket):
        return SignalEmissionRecord.objects.filter(
            team=self.team,
            source_product="conversations",
            source_type="ticket",
            source_id=str(ticket.id),
        ).exists()

    def test_creates_emission_record_after_fetch(self):
        ticket = _make_ticket(self.team)
        _backdate_ticket(ticket, hours=2)

        conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert self._has_emission(ticket)

    def test_does_not_create_emission_record_when_result_empty(self):
        ticket = _make_ticket(self.team)
        # ticket is too recent — no eligible tickets

        conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert not self._has_emission(ticket)

    def test_only_records_emission_for_fetched_tickets(self):
        eligible = _make_ticket(self.team, status="open")
        _backdate_ticket(eligible, hours=2)

        too_recent = _make_ticket(self.team, status="open")
        # too_recent is created now — within cooldown, so not fetched

        conversations_ticket_fetcher(self.team, CONVERSATIONS_TICKETS_CONFIG, {})

        assert self._has_emission(eligible)
        assert not self._has_emission(too_recent)
