from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.comment import Comment
from posthog.models.integration import Integration
from posthog.models.team import Team
from posthog.models.user import User

from products.conversations.backend.facade.api import (
    list_account_email_thread_messages,
    list_account_email_threads,
    list_email_threads_for_account_matching,
    replace_email_thread_account_links,
)
from products.conversations.backend.facade.types import EmailThreadAccountLinkInput
from products.conversations.backend.models import (
    EMAIL_THREAD_COMMENT_SCOPE,
    EmailThread,
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
    EmailThreadParticipant,
    EmailThreadParticipantKind,
)


class TestEmailThreadAccountLinks(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        sent_at = timezone.now()
        self.thread = EmailThread.objects.for_team(self.team.id).create(
            team=self.team,
            canonical_thread_key="<account-thread@example.com>",
            subject="Account review",
            first_message_at=sent_at,
            last_message_at=sent_at,
            message_count=1,
            preview="Latest update",
        )
        comment = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id=str(self.thread.id),
            content="Latest update",
        )
        self.message = EmailThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            thread=self.thread,
            comment=comment,
            message_id="<account-thread@example.com>",
            sent_at=sent_at,
            sender_email="customer@example.com",
            sender_name="Customer",
            to_recipients=[{"name": "CSM", "email": "csm@example.com"}],
            cc_recipients=[],
            sender_authenticated=True,
            direction=EmailThreadMessageDirection.INBOUND,
            source_type="mailgun",
            source_id="<account-thread@example.com>",
        )
        EmailThreadParticipant.objects.for_team(self.team.id).create(
            team=self.team,
            thread=self.thread,
            email="customer@example.com",
            display_name="Customer",
            kind=EmailThreadParticipantKind.CUSTOMER,
        )
        EmailThreadParticipant.objects.for_team(self.team.id).create(
            team=self.team,
            thread=self.thread,
            email="csm@example.com",
            display_name="CSM",
            kind=EmailThreadParticipantKind.INTERNAL,
        )

    def test_replaces_links_and_exposes_account_scoped_thread_contracts(self) -> None:
        matching_threads = list_email_threads_for_account_matching(self.team.id)
        assert len(matching_threads) == 1
        assert matching_threads[0].participant_emails == ["customer@example.com"]
        assert matching_threads[0].gmail_owner_id is None

        replace_email_thread_account_links(
            self.team.id,
            str(self.thread.id),
            [
                EmailThreadAccountLinkInput(
                    account_id="account-1",
                    account_external_id="group-1",
                    match_source="known_email",
                ),
                EmailThreadAccountLinkInput(
                    account_id="account-2",
                    account_external_id="group-2",
                    match_source="email_domain",
                ),
            ],
        )

        reply_sent_at = self.message.sent_at + timedelta(minutes=1)
        reply_comment = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id=str(self.thread.id),
            content="Reply update",
        )
        EmailThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            thread=self.thread,
            comment=reply_comment,
            message_id="<account-thread-reply@example.com>",
            in_reply_to=self.message.message_id,
            references=[self.message.message_id],
            sent_at=reply_sent_at,
            sender_email="csm@example.com",
            sender_name="CSM",
            to_recipients=[{"name": "Customer", "email": "customer@example.com"}],
            cc_recipients=[],
            sender_authenticated=True,
            direction=EmailThreadMessageDirection.OUTBOUND,
            source_type="mailgun",
            source_id="<account-thread-reply@example.com>",
        )
        self.thread.last_message_at = reply_sent_at
        self.thread.message_count = 2
        self.thread.preview = "Reply update"
        self.thread.save(update_fields=["last_message_at", "message_count", "preview", "updated_at"])

        summaries, count = list_account_email_threads(self.team.id, "account-1")
        message_page = list_account_email_thread_messages(self.team.id, "account-1", str(self.thread.id))
        assert count == 1
        assert len(summaries) == 1
        assert summaries[0].subject == "Account review"
        assert summaries[0].last_message is not None
        assert summaries[0].last_message.sender.name == "CSM"
        assert summaries[0].last_message.sender.email == "csm@example.com"
        assert summaries[0].last_message.sent_at == reply_sent_at
        assert summaries[0].last_message.direction == "outbound"
        assert message_page is not None
        messages, message_count = message_page
        assert message_count == 2
        assert messages[0].content == "Latest update"
        assert messages[0].sender_authenticated is True
        assert messages[0].to_recipients[0].email == "csm@example.com"

        replace_email_thread_account_links(
            self.team.id,
            str(self.thread.id),
            [
                EmailThreadAccountLinkInput(
                    account_id="account-2",
                    account_external_id="renamed-group-2",
                    match_source="organization_member",
                )
            ],
        )

        assert not EmailThreadAccountLink.objects.for_team(self.team.id).filter(account_id="account-1").exists()
        remaining = EmailThreadAccountLink.objects.for_team(self.team.id).get()
        assert remaining.account_external_id == "renamed-group-2"
        assert remaining.match_source == "organization_member"
        assert list_account_email_thread_messages(self.team.id, "account-1", str(self.thread.id)) is None

    def test_resolves_one_gmail_owner_across_integrations(self) -> None:
        first_integration = Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="first-gmail-owner",
            created_by=self.user,
        )
        second_integration = Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="second-gmail-owner",
            created_by=self.user,
        )
        self.message.source_type = "gmail"
        self.message.source_id = f"{first_integration.id}:gmail-message-1"
        self.message.save(update_fields=["source_type", "source_id"])
        second_comment = Comment.objects.create(
            team=self.team,
            scope=EMAIL_THREAD_COMMENT_SCOPE,
            item_id=str(self.thread.id),
            content="Second message",
        )
        second_message = EmailThreadMessage.objects.for_team(self.team.id).create(
            team=self.team,
            thread=self.thread,
            comment=second_comment,
            message_id="<second-account-thread@example.com>",
            sent_at=self.message.sent_at + timedelta(minutes=1),
            sender_email="customer@example.com",
            to_recipients=[],
            cc_recipients=[],
            direction=EmailThreadMessageDirection.INBOUND,
            source_type="gmail",
            source_id=f"{second_integration.id}:gmail-message-2",
        )

        [matching_thread] = list_email_threads_for_account_matching(self.team.id)

        assert matching_thread.gmail_owner_id == self.user.id

        other_owner = User.objects.create(email="other-owner@posthog.com")
        other_integration = Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="other-gmail-owner",
            created_by=other_owner,
        )
        second_message.source_id = f"{other_integration.id}:gmail-message-2"
        second_message.save(update_fields=["source_id"])

        [matching_thread] = list_email_threads_for_account_matching(self.team.id)

        assert matching_thread.gmail_owner_id is None

    def test_rejects_invalid_or_unowned_gmail_sources(self) -> None:
        unowned_integration = Integration.objects.create(
            team=self.team,
            kind="google-calendar",
            integration_id="unowned-gmail",
            created_by=None,
        )
        other_team = Team.objects.create(organization=self.organization)
        other_team_integration = Integration.objects.create(
            team=other_team,
            kind="google-calendar",
            integration_id="other-team-gmail",
            created_by=self.user,
        )
        other_kind_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="not-gmail",
            created_by=self.user,
        )
        self.message.source_type = "gmail"
        self.message.save(update_fields=["source_type"])

        for source_id in (
            "malformed",
            "999999999:gmail-message",
            f"{unowned_integration.id}:gmail-message",
            f"{other_team_integration.id}:gmail-message",
            f"{other_kind_integration.id}:gmail-message",
        ):
            with self.subTest(source_id=source_id):
                self.message.source_id = source_id
                self.message.save(update_fields=["source_id"])

                [matching_thread] = list_email_threads_for_account_matching(self.team.id)

                assert matching_thread.gmail_owner_id is None
