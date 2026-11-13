import json
import uuid
from collections.abc import Callable
from email import message_from_bytes, policy

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import Client

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.comment import Comment
from posthog.models.utils import generate_random_token_secret

from products.conversations.backend.api.tests.mailgun_signing import MailgunWebhookTestMixin, post_mailgun
from products.conversations.backend.models import EmailChannel, EmailOutboxMessage, Ticket
from products.conversations.backend.models.constants import Channel, EmailDelivery, Status
from products.conversations.backend.services.email_delivery import (
    MAX_CONFIRMATION_EMAILS_PER_RECIPIENT,
    EmailDeliveryUnavailable,
    request_email_delivery,
    stop_email_delivery,
)
from products.conversations.backend.services.messages import is_private_message
from products.conversations.backend.tasks.email import send_email_reply

CUSTOMER_EMAIL = "locked-out@customer.example"
INBOUND_TOKEN = "ab01cd23ef45"


class TestWidgetTicketEmailDelivery(MailgunWebhookTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"email_enabled": True}
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token=INBOUND_TOKEN,
            from_email="support@hedgebox.example",
            from_name="Hedgebox support",
            domain="hedgebox.example",
            domain_verified=True,
            is_default=True,
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            widget_session_id=str(uuid.uuid4()),
            distinct_id="anonymous-visitor-1",
            channel_source=Channel.WIDGET,
            status=Status.NEW,
            anonymous_traits={"name": "Typed by the visitor", "email": CUSTOMER_EMAIL},
            identity_verified=False,
        )
        self.url = f"/api/conversations/external/ticket/{self.ticket.id}"
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {self.team.secret_api_token}")
        self.webhook = Client()

        enqueue = patch("products.conversations.backend.services.email_delivery.send_email_reply")
        enqueue.start()
        self.addCleanup(enqueue.stop)

    def _patch(self, body: dict):
        return self.api.patch(self.url, body, format="json")

    def _send(self, outbox: EmailOutboxMessage):
        with patch("products.conversations.backend.tasks.email.send_mime") as send_mime:
            send_email_reply(str(outbox.id))
        outbox.refresh_from_db()
        return send_mime

    def _team_reply(self, content: str) -> Comment:
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            created_by=self.user,
            item_context={"author_type": "support", "is_private": False},
        )

    def _email_from(self, sender: str, *, in_reply_to: str, **fields: str):
        return post_mailgun(
            self.webhook,
            "/api/conversations/v1/email/inbound",
            {
                "recipient": f"team-{INBOUND_TOKEN}@mg.posthog.com",
                "sender": sender,
                "from": f"Customer <{sender}>",
                "Message-Id": f"<{uuid.uuid4()}@customer.example>",
                "In-Reply-To": in_reply_to,
                "stripped-text": "Yes, email me",
                "X-Mailgun-Spf": "Pass",
                **fields,
            },
        )

    def _request_and_send_confirmation(self) -> EmailOutboxMessage:
        request_email_delivery(self.ticket)
        confirmation = EmailOutboxMessage.objects.get(ticket=self.ticket)
        self._send(confirmation)
        return confirmation

    def test_confirmation_email_carries_no_ticket_or_visitor_content(self):
        request_email_delivery(self.ticket)
        confirmation = EmailOutboxMessage.objects.get(ticket=self.ticket)
        note = confirmation.comment

        send_mime = self._send(confirmation)

        assert send_mime.call_args.kwargs["recipients"] == [CUSTOMER_EMAIL]
        sent = message_from_bytes(send_mime.call_args.args[1], policy=policy.default)
        bodies = [part.get_content() for part in sent.walk() if part.get_content_maintype() == "text"]
        assert len(bodies) == 2
        for body in bodies:
            assert f"#{self.ticket.ticket_number}" in body
            assert "Typed by the visitor" not in body
            assert "Confirmation email sent" not in body
        assert is_private_message(note.item_context)
        assert confirmation.status == EmailOutboxMessage.Status.SENT

    @parameterized.expand(
        [
            ("ticket_address", CUSTOMER_EMAIL, {}, EmailDelivery.ACTIVE, 1),
            ("ticket_address_in_another_case", CUSTOMER_EMAIL.upper(), {}, EmailDelivery.ACTIVE, 1),
            ("another_address", "someone-else@customer.example", {}, EmailDelivery.PENDING, 0),
            (
                "auto_reply",
                CUSTOMER_EMAIL,
                {"message-headers": json.dumps([["Auto-Submitted", "auto-replied"]])},
                EmailDelivery.PENDING,
                0,
            ),
            ("sender_that_failed_authentication", CUSTOMER_EMAIL, {"X-Mailgun-Spf": "Fail"}, EmailDelivery.PENDING, 0),
        ]
    )
    def test_replies_are_emailed_only_after_the_customer_confirms(
        self, _name, sender, fields, expected_state, expected_outbox_rows
    ):
        confirmation = self._request_and_send_confirmation()
        held_reply = self._team_reply("Written before the customer confirmed")
        assert not EmailOutboxMessage.objects.filter(comment=held_reply).exists()

        self._email_from(sender, in_reply_to=confirmation.message_id, **fields)

        assert Ticket.objects.filter(team=self.team).count() == 1
        self.ticket.refresh_from_db()
        assert self.ticket.email_delivery == expected_state
        assert self.ticket.identity_verified is False
        assert EmailOutboxMessage.objects.filter(comment=held_reply).count() == expected_outbox_rows
        later_reply = self._team_reply("Written after the customer replied")
        assert EmailOutboxMessage.objects.filter(comment=later_reply).count() == expected_outbox_rows

    @parameterized.expand(
        [
            ("same_address", CUSTOMER_EMAIL, ["copied@customer.example"]),
            ("new_address", "moved@customer.example", []),
        ]
    )
    def test_second_request_is_confirmed_only_by_a_reply_to_its_own_confirmation(
        self, _name, second_address, expected_cc
    ):
        first = self._request_and_send_confirmation()
        self._email_from(CUSTOMER_EMAIL, in_reply_to=first.message_id)
        queued_for_first_address = EmailOutboxMessage.objects.get(comment=self._team_reply("For the first address"))
        stop_email_delivery(self.ticket)
        Ticket.objects.filter(id=self.ticket.id).update(
            cc_participants=["copied@customer.example"], anonymous_traits={"email": second_address}
        )

        request_email_delivery(self.ticket)
        second = (
            EmailOutboxMessage.objects.filter(ticket=self.ticket)
            .exclude(id__in=[first.id, queued_for_first_address.id])
            .get()
        )
        send_mime = self._send(second)
        self._email_from(second_address, in_reply_to=first.message_id)

        self.ticket.refresh_from_db()
        assert send_mime.call_args.kwargs["recipients"] == [second_address]
        assert message_from_bytes(send_mime.call_args.args[1], policy=policy.default)["In-Reply-To"] is None
        assert self.ticket.cc_participants == expected_cc
        assert self.ticket.email_delivery == EmailDelivery.PENDING
        self._email_from(second_address, in_reply_to=second.message_id)
        self._email_from("earlier@customer.example", in_reply_to=first.message_id, Cc="added-later@customer.example")
        self.ticket.refresh_from_db()
        assert self.ticket.email_delivery == EmailDelivery.ACTIVE
        assert self.ticket.cc_participants == expected_cc
        self._send(queued_for_first_address).assert_not_called()

    def test_widget_session_does_not_read_what_arrives_by_email(self):
        widget_token = "widget-token-for-email-delivery"
        self.team.conversations_settings = {"email_enabled": True, "widget_public_token": widget_token}
        self.team.save()
        confirmation = self._request_and_send_confirmation()
        with self.captureOnCommitCallbacks(execute=True):
            self._team_reply("Shown in the widget")
        with self.captureOnCommitCallbacks(execute=True):
            self._email_from(CUSTOMER_EMAIL, in_reply_to=confirmation.message_id)
        EmailChannel.objects.filter(id=self.config.id).delete()
        session = f"widget_session_id={self.ticket.widget_session_id}"

        messages = self.api.get(
            f"/api/conversations/v1/widget/messages/{self.ticket.id}?{session}", HTTP_X_CONVERSATIONS_TOKEN=widget_token
        )
        tickets = self.api.get(
            f"/api/conversations/v1/widget/tickets?{session}", HTTP_X_CONVERSATIONS_TOKEN=widget_token
        )

        assert Ticket.objects.get(id=self.ticket.id).last_message_text == "Yes, email me"
        assert [message["content"] for message in messages.json()["messages"]] == ["Shown in the widget"]
        assert [ticket["last_message"] for ticket in tickets.json()["results"]] == ["Shown in the widget"]

    def test_replies_behind_many_customer_messages_are_still_emailed_on_confirmation(self):
        confirmation = self._request_and_send_confirmation()
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="Another message from the widget",
            item_context={"author_type": "customer", "is_private": False},
        )
        held_reply = self._team_reply("Written before the customer confirmed")

        with patch("products.conversations.backend.services.email_delivery.MAX_REPLIES_SENT_ON_CONFIRMATION", 1):
            self._email_from(CUSTOMER_EMAIL, in_reply_to=confirmation.message_id)

        assert EmailOutboxMessage.objects.filter(comment=held_reply).exists()

    def test_an_address_gets_a_limited_number_of_confirmation_emails(self):
        def request_on_a_new_ticket() -> None:
            ticket = Ticket.objects.create_with_number(
                team=self.team,
                widget_session_id=str(uuid.uuid4()),
                distinct_id=str(uuid.uuid4()),
                channel_source=Channel.WIDGET,
                status=Status.NEW,
                anonymous_traits={"email": CUSTOMER_EMAIL.upper()},
            )
            request_email_delivery(ticket)

        for _ in range(MAX_CONFIRMATION_EMAILS_PER_RECIPIENT):
            request_on_a_new_ticket()

        with self.assertRaises(EmailDeliveryUnavailable):
            request_on_a_new_ticket()
        assert self._patch({"email_delivery": True}).status_code == status.HTTP_400_BAD_REQUEST

    def test_queued_reply_is_not_sent_after_delivery_is_turned_off(self):
        confirmation = self._request_and_send_confirmation()
        self._email_from(CUSTOMER_EMAIL, in_reply_to=confirmation.message_id)
        queued = EmailOutboxMessage.objects.get(comment=self._team_reply("Queued while delivery was active"))

        stop_email_delivery(self.ticket)
        send_mime = self._send(queued)

        send_mime.assert_not_called()
        assert queued.status == EmailOutboxMessage.Status.FAILED_PERMANENT

    def test_update_action_sends_one_confirmation_and_reports_the_state(self):
        with (
            patch("products.conversations.backend.services.email_delivery.report_team_action") as report,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert self._patch({"email_delivery": True}).status_code == status.HTTP_200_OK
            assert self._patch({"email_delivery": True}).status_code == status.HTTP_200_OK

            assert EmailOutboxMessage.objects.filter(ticket=self.ticket).count() == 1
            assert self.api.get(self.url).json()["email_delivery"] == "pending"

            assert self._patch({"email_delivery": False}).status_code == status.HTTP_200_OK
            assert self.api.get(self.url).json()["email_delivery"] == "off"

        assert [call.args[1] for call in report.call_args_list] == [
            "support ticket email delivery requested",
            "support ticket email delivery stopped",
        ]

    def test_email_ticket_reports_active_and_stays_active(self):
        Ticket.objects.filter(id=self.ticket.id).update(channel_source=Channel.EMAIL)

        response = self._patch({"email_delivery": False})

        assert response.status_code == status.HTTP_200_OK
        assert self.api.get(self.url).json()["email_delivery"] == "active"

    @parameterized.expand(
        [
            ("no_customer_email", lambda t: Ticket.objects.filter(id=t.ticket.id).update(anonymous_traits={})),
            (
                "invalid_customer_email",
                lambda t: Ticket.objects.filter(id=t.ticket.id).update(anonymous_traits={"email": "not an address"}),
            ),
            (
                "customer_email_longer_than_the_column",
                lambda t: Ticket.objects.filter(id=t.ticket.id).update(
                    anonymous_traits={"email": f"{'a' * 64}@{'b' * 200}.example"}
                ),
            ),
            ("slack_ticket", lambda t: Ticket.objects.filter(id=t.ticket.id).update(channel_source=Channel.SLACK)),
            (
                "email_channel_off",
                lambda t: type(t.team).objects.filter(id=t.team.id).update(conversations_settings={}),
            ),
            (
                "no_verified_default_address",
                lambda t: EmailChannel.objects.filter(id=t.config.id).update(domain_verified=False),
            ),
        ]
    )
    def test_update_action_refuses_and_saves_nothing(self, _name, arrange: Callable):
        arrange(self)

        response = self._patch({"email_delivery": True, "status": "open"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        self.ticket.refresh_from_db()
        assert self.ticket.email_delivery is None
        assert self.ticket.status == Status.NEW
        assert not EmailOutboxMessage.objects.filter(ticket=self.ticket).exists()
