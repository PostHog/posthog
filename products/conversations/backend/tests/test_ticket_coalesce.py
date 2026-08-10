from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.ticket_coalesce import (
    APPEND_WINDOW_SECONDS,
    IDENTICAL_REPLAY_WINDOW_SECONDS,
    AppendTarget,
    ReplayTarget,
    resolve,
)


class TestTicketCoalesceResolve(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.widget_session_id = "11111111-1111-4111-8111-111111111111"
        self.now = timezone.now()

    def _ticket(self, **overrides: object) -> Ticket:
        fields: dict[str, object] = {
            "team": self.team,
            "widget_session_id": self.widget_session_id,
            "distinct_id": "customer-1",
            "channel_source": "widget",
            "status": "new",
        }
        fields.update(overrides)
        return Ticket.objects.create_with_number(**fields)

    def _customer_comment(self, ticket: Ticket, content: str, **overrides: object) -> Comment:
        fields: dict[str, object] = {
            "team": self.team,
            "scope": "conversations_ticket",
            "item_id": str(ticket.id),
            "content": content,
            "item_context": {"author_type": "customer", "distinct_id": "customer-1", "is_private": False},
        }
        fields.update(overrides)
        return Comment.objects.create(**fields)

    def test_appends_recent_unanswered_ticket_with_different_text(self) -> None:
        ticket = self._ticket()
        self._customer_comment(ticket, "First attempt")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Retyped with different wording",
            now=self.now,
        )

        self.assertEqual(target, AppendTarget(ticket=ticket))

    def test_replays_identical_text_inside_replay_window(self) -> None:
        ticket = self._ticket()
        comment = self._customer_comment(ticket, "Same body twice")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Same body twice",
            now=self.now,
        )

        self.assertEqual(target, ReplayTarget(ticket=ticket, comment=comment))

    def test_appends_to_newest_ticket_instead_of_replaying_older_candidate(self) -> None:
        with freeze_time(self.now - timedelta(seconds=20)):
            older = self._ticket()
            self._customer_comment(older, "Original wording")
        with freeze_time(self.now - timedelta(seconds=10)):
            newer = self._ticket()
            self._customer_comment(newer, "Different follow-up wording")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Original wording",
            now=self.now,
        )

        self.assertEqual(target, AppendTarget(ticket=newer))

    def test_appends_repeated_text_when_a_different_message_intervened(self) -> None:
        ticket = self._ticket()
        with freeze_time(self.now - timedelta(seconds=20)):
            self._customer_comment(ticket, "Repeated wording")
        with freeze_time(self.now - timedelta(seconds=10)):
            self._customer_comment(ticket, "Intervening message")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Repeated wording",
            now=self.now,
        )

        self.assertEqual(target, AppendTarget(ticket=ticket))

    def test_replays_when_identical_text_is_the_latest_of_multiple_messages(self) -> None:
        ticket = self._ticket()
        with freeze_time(self.now - timedelta(seconds=20)):
            self._customer_comment(ticket, "Earlier message")
        with freeze_time(self.now - timedelta(seconds=10)):
            latest_comment = self._customer_comment(ticket, "Repeated wording")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Repeated wording",
            now=self.now,
        )

        self.assertEqual(target, ReplayTarget(ticket=ticket, comment=latest_comment))

    @parameterized.expand(
        [
            ("support_reply", {"author_type": "support", "is_private": False}),
            ("ai_reply", {"author_type": "AI", "is_private": False}),
            ("team_reply", {"author_type": "team", "is_private": False}),
            ("unknown_reply", {"author_type": "other", "is_private": False}),
            ("missing_author_type", {"is_private": False}),
        ]
    )
    def test_creates_when_candidate_has_non_customer_comment(self, _name: str, item_context: dict[str, object]) -> None:
        ticket = self._ticket()
        self._customer_comment(ticket, "Customer opener")
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(ticket.id),
            content="We looked into it",
            item_context=item_context,
        )

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Follow-up that should be a new ticket",
            now=self.now,
        )

        self.assertIsNone(target)

    def test_creates_when_candidate_is_resolved(self) -> None:
        ticket = self._ticket(status=Status.RESOLVED)
        self._customer_comment(ticket, "Already closed out")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="New question after resolve",
            now=self.now,
        )

        self.assertIsNone(target)

    def test_creates_when_widget_session_differs(self) -> None:
        ticket = self._ticket()
        self._customer_comment(ticket, "Hello")

        target = resolve(
            team_id=self.team.id,
            widget_session_id="22222222-2222-4222-8222-222222222222",
            content="Hello",
            now=self.now,
        )

        self.assertIsNone(target)

    def test_creates_when_candidate_older_than_both_windows(self) -> None:
        with freeze_time(self.now - timedelta(seconds=APPEND_WINDOW_SECONDS + 1)):
            ticket = self._ticket()
            self._customer_comment(ticket, "Stale opener")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="New question after the windows",
            now=self.now,
        )

        self.assertIsNone(target)

    def test_appends_identical_text_outside_replay_window(self) -> None:
        age = IDENTICAL_REPLAY_WINDOW_SECONDS + 1
        assert age < APPEND_WINDOW_SECONDS
        with freeze_time(self.now - timedelta(seconds=age)):
            ticket = self._ticket()
            self._customer_comment(ticket, "Exact same body")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Exact same body",
            now=self.now,
        )

        self.assertEqual(target, AppendTarget(ticket=ticket))

    def test_appends_when_recent_comment_has_not_updated_last_message_at_yet(self) -> None:
        with freeze_time(self.now - timedelta(seconds=APPEND_WINDOW_SECONDS + 1)):
            ticket = self._ticket()
        with freeze_time(self.now - timedelta(seconds=5)):
            self._customer_comment(ticket, "Recent message on an older ticket")

        target = resolve(
            team_id=self.team.id,
            widget_session_id=self.widget_session_id,
            content="Retried message",
            now=self.now,
        )

        self.assertEqual(target, AppendTarget(ticket=ticket))
