from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models import Comment

from products.conversations.backend.ai.subject import (
    SUBJECT_GENERATION_SETTING,
    _clean_subject,
    should_generate_subject,
)
from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.tasks import generate_ticket_subject

FLAG_PATH = "products.conversations.backend.feature_flags.is_ai_subject_generation_enabled"
# generate_subject imports get_llm_client lazily from its source module (startup-time deferral),
# so patch it there rather than on the ai.subject namespace.
GET_LLM_CLIENT_PATH = "posthog.llm.gateway_client.get_llm_client"


def _mock_ticket(*, opted_in=True, email_subject=None, approved=True, current_subject=None):
    org = MagicMock()
    org.is_ai_data_processing_approved = approved
    team = MagicMock()
    team.organization = org
    team.conversations_settings = {SUBJECT_GENERATION_SETTING: opted_in}
    ticket = MagicMock()
    ticket.team = team
    ticket.email_subject = email_subject
    ticket.subject = current_subject
    return ticket


class TestCleanSubject:
    @parameterized.expand(
        [
            ("keep_sentinel_yields_none", "KEEP", None),
            ("keep_sentinel_case_insensitive", "keep", None),
            ("empty_yields_none", "   ", None),
            ("strips_wrapping_quotes", '"Billing export fails"', "Billing export fails"),
            ("takes_first_line_only", "Login redirect loop\nsome rambling", "Login redirect loop"),
            ("plain_passthrough", "Cannot connect Stripe source", "Cannot connect Stripe source"),
        ]
    )
    def test_clean_subject(self, _name, raw, expected):
        assert _clean_subject(raw) == expected

    def test_truncates_to_max_length(self):
        assert len(_clean_subject("x" * 500) or "") == 200


class TestShouldGenerateSubject:
    @parameterized.expand(
        [
            ("all_gates_pass", {}, True),
            ("opt_in_off", {"opted_in": False}, False),
            ("channel_provided_subject_is_untouchable", {"email_subject": "Re: my invoice"}, False),
            ("ai_processing_not_approved", {"approved": False}, False),
        ]
    )
    def test_gating(self, _name, overrides, expected):
        assert should_generate_subject(_mock_ticket(**overrides)) is expected


def _llm_returning(content: str):
    """Build a get_llm_client stand-in whose chat completion returns `content`."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return MagicMock(return_value=client)


@patch(FLAG_PATH, return_value=True)
class TestGenerateTicketSubjectTask(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {SUBJECT_GENERATION_SETTING: True}
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="s-1",
            distinct_id="u-1",
            status=Status.NEW,
        )
        Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="The billing CSV export returns a 500 every time",
            item_context={"author_type": "customer", "is_private": False},
        )

    def test_writes_generated_subject(self, _flag):
        with patch(GET_LLM_CLIENT_PATH, _llm_returning("Billing export returns 500")):
            generate_ticket_subject(str(self.ticket.id), self.team.id)
        self.ticket.refresh_from_db()
        assert self.ticket.subject == "Billing export returns 500"

    def test_keep_leaves_existing_subject(self, _flag):
        Ticket.objects.filter(id=self.ticket.id).update(subject="Billing export broken")
        with patch(GET_LLM_CLIENT_PATH, _llm_returning("KEEP")):
            generate_ticket_subject(str(self.ticket.id), self.team.id)
        self.ticket.refresh_from_db()
        assert self.ticket.subject == "Billing export broken"

    def test_channel_provided_subject_never_overwritten(self, _flag):
        Ticket.objects.filter(id=self.ticket.id).update(channel_source=Channel.EMAIL, email_subject="Re: my invoice")
        client_factory = _llm_returning("Something the AI made up")
        with patch(GET_LLM_CLIENT_PATH, client_factory):
            generate_ticket_subject(str(self.ticket.id), self.team.id)
        self.ticket.refresh_from_db()
        assert self.ticket.subject is None
        client_factory.assert_not_called()  # gated out before spending on the LLM


class TestSubjectSignalTrigger(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.conversations_settings = {SUBJECT_GENERATION_SETTING: True}
        self.team.save()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="s-1",
            distinct_id="u-1",
            status=Status.NEW,
        )

    @parameterized.expand([("public_message_enqueues", False, True), ("private_note_skipped", True, False)])
    def test_enqueue_on_public_only(self, _name, is_private, expected_enqueued):
        with patch("products.conversations.backend.signals.generate_ticket_subject") as mock_task:
            with self.captureOnCommitCallbacks(execute=True):
                Comment.objects.create(
                    team=self.team,
                    scope="conversations_ticket",
                    item_id=str(self.ticket.id),
                    content="hello",
                    item_context={"author_type": "customer", "is_private": is_private},
                )
        assert mock_task.delay.called is expected_enqueued
