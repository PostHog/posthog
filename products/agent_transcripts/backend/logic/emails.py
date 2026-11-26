"""The email that tells the person who submitted a transcript what staff decided."""

from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.db import transaction

import structlog

from posthog.dataclasses import frozen
from posthog.email import EmailMessage, get_email_team_and_org_context, is_email_available
from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.models.user import User

from ..facade.contracts import MERCH_CODE_VALUE_USD, TRANSCRIPT_RETENTION_DAYS
from ..facade.enums import SubmissionStatus
from ..models import AgentTranscriptSubmission

logger = structlog.get_logger(__name__)

APPROVED_WITH_CODE_TEMPLATE = "agent_transcript_approved_with_code"
APPROVED_TEMPLATE = "agent_transcript_approved"
CHANGES_REQUESTED_TEMPLATE = "agent_transcript_changes_requested"
DECLINED_TEMPLATE = "agent_transcript_declined"

SUBJECTS = {
    APPROVED_WITH_CODE_TEMPLATE: "Your transcript was accepted: here's your merch code",
    APPROVED_TEMPLATE: "Your transcript was accepted",
    CHANGES_REQUESTED_TEMPLATE: "Your transcript needs changes",
    DECLINED_TEMPLATE: "Your transcript wasn't accepted",
}

MERCH_STORE_URL = "https://posthog.com/merch"
# The merch store reads the code from this query parameter and applies it at checkout.
MERCH_COUPON_PARAMETER = "coupon"
SUBMISSION_PAGE_PATH = "/agent-transcript"


@frozen
class DecisionEmail:
    """The decision as it committed, so the email describes that decision even if the row changes later."""

    submission_id: UUID
    organization_id: UUID
    submitter_id: int
    status: SubmissionStatus
    reviewed_at: datetime
    review_message: str | None
    merch_code: str | None


def decision_template(status: SubmissionStatus, merch_code: str | None) -> str:
    if status == SubmissionStatus.APPROVED:
        return APPROVED_WITH_CODE_TEMPLATE if merch_code else APPROVED_TEMPLATE
    if status == SubmissionStatus.CHANGES_REQUESTED:
        return CHANGES_REQUESTED_TEMPLATE
    if status == SubmissionStatus.DECLINED:
        return DECLINED_TEMPLATE
    raise ValueError(f"No decision email for a submission in status {status.value}")


def merch_url(merch_code: str) -> str:
    return f"{MERCH_STORE_URL}?{urlencode({MERCH_COUPON_PARAMETER: merch_code})}"


def schedule_decision_email(submission: AgentTranscriptSubmission) -> None:
    """Email the submitter once the decision commits, so a decision that rolls back sends nothing."""
    if submission.submitted_by_id is None or submission.reviewed_at is None:
        return

    email = DecisionEmail(
        submission_id=submission.id,
        organization_id=submission.organization_id,
        submitter_id=submission.submitted_by_id,
        status=SubmissionStatus(submission.status),
        reviewed_at=submission.reviewed_at,
        review_message=submission.review_message,
        merch_code=submission.merch_code,
    )
    transaction.on_commit(lambda: send_decision_email(email))


def send_decision_email(email: DecisionEmail) -> None:
    try:
        _send(email)
    except Exception as error:
        # The decision has already committed, so a failed email must not fail the request that made it.
        logger.exception("agent_transcripts.decision_email_failed", submission_id=str(email.submission_id))
        capture_exception(error, additional_properties={"submission_id": str(email.submission_id)})


def _send(email: DecisionEmail) -> None:
    if not is_email_available(with_absolute_urls=True):
        return

    submitter = User.objects.filter(id=email.submitter_id, is_active=True).first()
    if submitter is None or not submitter.email:
        return

    template_name = decision_template(email.status, email.merch_code)
    organization = Organization.objects.filter(id=email.organization_id).first()

    message = EmailMessage(
        campaign_key=f"agent_transcript_{email.submission_id}_{email.status.value}_{email.reviewed_at.timestamp()}",
        subject=SUBJECTS[template_name],
        template_name=template_name,
        template_context={
            **template_variables(template_name, email, submitter),
            **get_email_team_and_org_context(organization=organization),
        },
        use_http=True,
    )
    message.add_user_recipient(submitter)
    message.send()


def submission_url(submitter: User, organization_id: UUID) -> str:
    """A link to the submission page inside one of the organization's projects.

    The page shows the submission of the submitter's current organization. A project in the address
    makes the server switch the submitter into that project's organization first.
    """
    team_ids = list(submitter.teams.filter(organization_id=organization_id).values_list("id", flat=True))
    if not team_ids:
        return f"{settings.SITE_URL}{SUBMISSION_PAGE_PATH}"

    team_id = submitter.current_team_id if submitter.current_team_id in team_ids else team_ids[0]
    return f"{settings.SITE_URL}/project/{team_id}{SUBMISSION_PAGE_PATH}"


def template_variables(template_name: str, email: DecisionEmail, submitter: User) -> dict[str, object]:
    """The variables each template reads. The Workflows template with the same key reads the same names."""
    variables: dict[str, object] = {"retention_days": TRANSCRIPT_RETENTION_DAYS}

    if template_name == APPROVED_WITH_CODE_TEMPLATE and email.merch_code is not None:
        variables["merch_code"] = email.merch_code
        variables["merch_url"] = merch_url(email.merch_code)
        variables["merch_value_usd"] = MERCH_CODE_VALUE_USD
    if template_name in (CHANGES_REQUESTED_TEMPLATE, DECLINED_TEMPLATE):
        variables["review_message"] = email.review_message or ""
    if template_name == CHANGES_REQUESTED_TEMPLATE:
        variables["submission_url"] = submission_url(submitter, email.organization_id)

    return variables
