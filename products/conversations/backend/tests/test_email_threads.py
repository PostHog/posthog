from datetime import datetime, timedelta

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailThread,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
    Ticket,
)
from products.conversations.backend.services.email_threads import delete_email_thread


class TestEmailThreadPersistence(BaseTest):
    def _create_thread(self, *, canonical_thread_key: str = "<root@example.com>") -> EmailThread:
        return EmailThread.objects.for_team(self.team.id).create(
            team=self.team,
            canonical_thread_key=canonical_thread_key,
            subject="Quarterly planning",
        )

    def _create_message(
        self,
        thread: EmailThread,
        *,
        source_id: str,
        message_id: str,
        sent_at: datetime,
        direction: str = EmailThreadMessageDirection.INBOUND,
    ) -> EmailThreadMessage:
        comment = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id=str(thread.id),
            content=f"Body for {source_id}",
        )
        return EmailThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            thread=thread,
            comment=comment,
            message_id=message_id,
            in_reply_to="<root@example.com>" if direction == EmailThreadMessageDirection.OUTBOUND else None,
            references=["<root@example.com>"],
            sent_at=sent_at,
            sender_email="sender@example.com",
            sender_name="Example sender",
            to_recipients=[{"email": "owner@example.com", "name": "Owner"}],
            cc_recipients=[{"email": "observer@example.com", "name": "Observer"}],
            direction=direction,
            source_type="mailgun",
            source_id=source_id,
        )

    def test_messages_use_source_timestamp_order_and_preserve_email_metadata(self) -> None:
        thread = self._create_thread()
        later = timezone.now()
        outbound = self._create_message(
            thread,
            source_id="provider-2",
            message_id="<reply@example.com>",
            sent_at=later,
            direction=EmailThreadMessageDirection.OUTBOUND,
        )
        inbound = self._create_message(
            thread,
            source_id="provider-1",
            message_id="<root@example.com>",
            sent_at=later - timedelta(hours=1),
        )

        messages = list(EmailThreadMessage.objects.for_team(self.team.id).filter(thread=thread))

        assert [message.id for message in messages] == [inbound.id, outbound.id]
        assert outbound.comment.scope == EMAIL_THREAD_COMMENT_SCOPE
        assert outbound.comment.item_id == str(thread.id)
        assert outbound.comment.source_comment_id is None
        assert outbound.in_reply_to == "<root@example.com>"
        assert outbound.references == ["<root@example.com>"]
        assert outbound.to_recipients == [{"email": "owner@example.com", "name": "Owner"}]
        assert outbound.cc_recipients == [{"email": "observer@example.com", "name": "Observer"}]
        assert outbound.direction == EmailThreadMessageDirection.OUTBOUND
        assert outbound.source_type == "mailgun"
        assert outbound.source_id == "provider-2"

    def test_email_thread_comments_do_not_update_matching_ticket_stats(self) -> None:
        thread = self._create_thread()
        ticket = Ticket.objects.create(
            id=thread.id,
            team=self.team,
            ticket_number=1,
            widget_session_id="email-thread-scope-test",
            distinct_id="example-customer",
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._create_message(
                thread,
                source_id="provider-1",
                message_id="<root@example.com>",
                sent_at=timezone.now(),
            )

        ticket.refresh_from_db()
        assert ticket.message_count == 0
        assert ticket.unread_customer_count == 0
        assert ticket.unread_team_count == 0
        assert ticket.last_message_at is None
        assert ticket.last_message_text is None

    @parameterized.expand(
        [
            ("provider_identity", "provider-1", "<different@example.com>"),
            ("rfc_message_id", "provider-2", "<root@example.com>"),
        ]
    )
    def test_duplicate_canonical_messages_are_rejected(
        self, _name: str, duplicate_source_id: str, duplicate_message_id: str
    ) -> None:
        thread = self._create_thread()
        sent_at = timezone.now()
        self._create_message(
            thread,
            source_id="provider-1",
            message_id="<root@example.com>",
            sent_at=sent_at,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_message(
                thread,
                source_id=duplicate_source_id,
                message_id=duplicate_message_id,
                sent_at=sent_at,
            )

    def test_messages_without_rfc_ids_do_not_collide(self) -> None:
        thread = self._create_thread()
        sent_at = timezone.now()

        first = self._create_message(
            thread,
            source_id="provider-1",
            message_id="",
            sent_at=sent_at,
        )
        second = self._create_message(
            thread,
            source_id="provider-2",
            message_id="",
            sent_at=sent_at,
        )

        assert first.id != second.id

    def test_canonical_thread_key_is_unique_per_team(self) -> None:
        self._create_thread()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_thread()

    def test_delete_service_removes_envelopes_participants_and_all_thread_comments(self) -> None:
        thread = self._create_thread()
        message = self._create_message(
            thread,
            source_id="provider-1",
            message_id="<root@example.com>",
            sent_at=timezone.now(),
        )
        EmailThreadParticipant.objects.for_team(self.team.id).create(
            team=self.team,
            thread=thread,
            email="customer@example.com",
            display_name="Example customer",
            kind=EmailThreadParticipantKind.CUSTOMER,
        )
        orphaned_content = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id=str(thread.id),
            content="Captured before its envelope was written",
        )
        unrelated = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id="different-thread",
            content="Keep this content",
        )

        delete_email_thread(team_id=self.team.id, thread_id=thread.id)

        assert not EmailThread.objects.for_team(self.team.id).filter(id=thread.id).exists()
        assert not EmailThreadMessage.objects.for_team(self.team.id).filter(id=message.id).exists()
        assert not EmailThreadParticipant.objects.for_team(self.team.id).filter(thread_id=thread.id).exists()
        assert not Comment.objects.filter(id__in=[message.comment_id, orphaned_content.id]).exists()
        assert Comment.objects.filter(id=unrelated.id).exists()
