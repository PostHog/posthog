from collections.abc import Callable
from email.utils import parseaddr
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest

from django.conf import settings
from django.core import mail
from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization
from posthog.models.user import User

from products.agent_transcripts.backend.facade import api
from products.agent_transcripts.backend.facade.contracts import MERCH_CODE_VALUE_USD, TRANSCRIPT_RETENTION_DAYS
from products.agent_transcripts.backend.facade.enums import SubmissionStatus, TranscriptAgent
from products.agent_transcripts.backend.models import AgentTranscriptSubmission

SUBMITTER_EMAIL = "submitter@example.com"
MERCH_CODE = "AGENT-0042"
CUSTOMER_MESSAGE = "Upload the whole conversation, from the first prompt to the end."
INTERNAL_NOTE = "Only the last few messages were in the file."
RETENTION_SENTENCE = f"{TRANSCRIPT_RETENTION_DAYS} days after upload"
MERCH_LINK = f"https://posthog.com/merch?coupon={MERCH_CODE}"
MERCH_VALUE = f"${MERCH_CODE_VALUE_USD}"


def _approve_with_code(organization_id: UUID, reviewer_id: int) -> Any:
    return api.approve_submission(
        organization_id=organization_id, reviewer_id=reviewer_id, review_note=INTERNAL_NOTE, merch_code=MERCH_CODE
    )


def _approve_without_code(organization_id: UUID, reviewer_id: int) -> Any:
    return api.approve_submission(organization_id=organization_id, reviewer_id=reviewer_id, review_note=INTERNAL_NOTE)


def _request_changes(organization_id: UUID, reviewer_id: int) -> Any:
    return api.request_changes(
        organization_id=organization_id,
        reviewer_id=reviewer_id,
        review_note=INTERNAL_NOTE,
        review_message=CUSTOMER_MESSAGE,
    )


def _decline(organization_id: UUID, reviewer_id: int) -> Any:
    return api.decline_submission(
        organization_id=organization_id,
        reviewer_id=reviewer_id,
        review_note=INTERNAL_NOTE,
        review_message=CUSTOMER_MESSAGE,
    )


class TestDecisionEmails(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        self.enterContext(override_instance_config("EMAIL_HOST", "localhost"))
        self.submitter = User.objects.create_and_join(self.organization, SUBMITTER_EMAIL, None, first_name="Ada")
        AgentTranscriptSubmission.objects.create(
            organization=self.organization,
            status=SubmissionStatus.SUBMITTED,
            agent=TranscriptAgent.CLAUDE_CODE,
            original_filename="conversation.jsonl",
            submitted_by=self.submitter,
            submitted_at=timezone.now(),
        )

    @parameterized.expand(
        [
            (
                "approved_with_code",
                _approve_with_code,
                "Your transcript was accepted: here's your merch code",
                [MERCH_CODE, MERCH_LINK, MERCH_VALUE],
                [INTERNAL_NOTE],
            ),
            (
                "approved_without_code",
                _approve_without_code,
                "Your transcript was accepted",
                [],
                ["merch", "reward", "coupon", MERCH_VALUE, INTERNAL_NOTE],
            ),
            (
                "changes_requested",
                _request_changes,
                "Your transcript needs changes",
                [CUSTOMER_MESSAGE],
                ["merch", INTERNAL_NOTE],
            ),
            (
                "declined",
                _decline,
                "Your transcript wasn't accepted",
                [CUSTOMER_MESSAGE],
                ["merch", INTERNAL_NOTE],
            ),
        ]
    )
    def test_decision_emails_the_submitter_once(
        self,
        _name: str,
        decide: Callable[[UUID, int], Any],
        subject: str,
        expected_text: list[str],
        unexpected_text: list[str],
    ) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            decide(self.organization.id, self.user.id)

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert isinstance(email, mail.EmailMultiAlternatives)
        html_body = str(email.alternatives[0][0])
        assert [parseaddr(address)[1] for address in email.to] == [SUBMITTER_EMAIL]
        assert email.subject == subject
        assert RETENTION_SENTENCE in html_body
        for text in expected_text:
            assert text in html_body
        for text in unexpected_text:
            assert text.lower() not in html_body.lower()

    @parameterized.expand([("in_the_submission_organization", False), ("in_another_organization", True)])
    def test_changes_requested_link_opens_the_submission_organization(self, _name: str, switched_away: bool) -> None:
        if switched_away:
            Organization.objects.bootstrap(self.submitter, name="Another organization")

        with self.captureOnCommitCallbacks(execute=True):
            _request_changes(self.organization.id, self.user.id)

        email = mail.outbox[0]
        assert isinstance(email, mail.EmailMultiAlternatives)
        html_body = str(email.alternatives[0][0])
        assert f'href="{settings.SITE_URL}/project/{self.team.id}/agent-transcript"' in html_body
