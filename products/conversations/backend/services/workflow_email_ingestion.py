import re
from datetime import datetime

from django.db import transaction
from django.db.models.functions import Lower

import posthoganalytics

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.conversations.backend.models import (
    EmailThreadAccountLink,
    EmailThreadMessage,
    EmailThreadMessageDirection,
)
from products.conversations.backend.services.email_thread_ingestion import (
    EmailAddress,
    EmailThreadIngestionResult,
    ParsedEmail,
    ingest_customer_email,
)
from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_CSP_FLAG
from products.customer_analytics.backend.facade.email_matching import match_email_accounts

_SES_MESSAGE_ID_RE = re.compile(r"[A-Za-z0-9-]{1,250}\Z")


def get_ses_rfc_message_id(provider_message_id: str) -> str:
    if not _SES_MESSAGE_ID_RE.fullmatch(provider_message_id):
        raise ValueError("Invalid SES message ID")
    return f"<{provider_message_id}@email.amazonses.com>"


def is_workflow_email_capture_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    enabled = posthoganalytics.feature_enabled(
        CUSTOMER_ANALYTICS_CSP_FLAG,
        organization_id,
        groups={"organization": organization_id},
        only_evaluate_locally=False,
        send_feature_flag_events=False,
    )
    if enabled is None:
        raise RuntimeError("Workflow email capture flag could not be evaluated")
    return bool(enabled)


def get_verified_workflow_sender(*, team_id: int, integration_id: int, sender_email: str) -> bool:
    integration = Integration.objects.filter(
        team_id=team_id, id=integration_id, kind=Integration.IntegrationKind.EMAIL
    ).first()
    if integration is None:
        return False
    configured_email = integration.config.get("email", "")
    verified_domain = integration.config.get("domain") or configured_email.rsplit("@", 1)[-1]
    return bool(
        integration.config.get("verified")
        and configured_email
        and verified_domain
        and sender_email.lower().rsplit("@", 1)[-1] == verified_domain.lower()
    )


def get_external_workflow_recipients(team: Team, sender_email: str, to_email: str, cc_emails: list[str]) -> list[str]:
    recipients = {email.strip().lower() for email in [to_email, *cc_emails] if email.strip()}
    recipients.discard(sender_email.strip().lower())
    internal_emails = set(
        OrganizationMembership.objects.filter(organization_id=team.organization_id, user__is_active=True)
        .annotate(normalized_member_email=Lower("user__email"))
        .filter(normalized_member_email__in=recipients)
        .values_list("normalized_member_email", flat=True)
    )
    return sorted(recipients - internal_emails)


def has_workflow_email_account_match(team: Team, sender_email: str, to_email: str, cc_emails: list[str]) -> bool:
    return bool(
        match_email_accounts(team.id, get_external_workflow_recipients(team, sender_email, to_email, cc_emails))
    )


def ingest_workflow_email(
    *,
    team: Team,
    source_id: str,
    provider_message_id: str,
    sent_at: datetime,
    sender: EmailAddress,
    to_recipient: EmailAddress,
    cc_recipients: tuple[EmailAddress, ...],
    subject: str,
    body_plain: str,
) -> EmailThreadIngestionResult | None:
    existing = EmailThreadMessage.objects.for_team(team.id).filter(source_type="workflow", source_id=source_id).first()
    if existing is not None:
        return EmailThreadIngestionResult(thread_id=existing.thread_id, message_id=existing.id, created=False)

    matches = match_email_accounts(
        team.id,
        get_external_workflow_recipients(
            team, sender.email, to_recipient.email, [recipient.email for recipient in cc_recipients]
        ),
    )
    if not matches:
        return None

    email = ParsedEmail(
        message_id=get_ses_rfc_message_id(provider_message_id),
        in_reply_to=None,
        references=(),
        sent_at=sent_at,
        sender=sender,
        to_recipients=(to_recipient,),
        cc_recipients=cc_recipients,
        subject=subject,
        body_plain=body_plain,
        stripped_text=body_plain,
        sender_authenticated=True,
        dkim_passed=False,
        dkim_signing_domains=(),
        capture_address="",
        attachments=(),
    )
    with transaction.atomic():
        result = ingest_customer_email(
            team_id=team.id,
            channel=None,
            email=email,
            direction=EmailThreadMessageDirection.OUTBOUND,
            source_type="workflow",
            source_id=source_id,
            internal_sender_email=sender.email,
        )
        if result.created:
            for match in matches:
                EmailThreadAccountLink.objects.for_team(team.id).get_or_create(
                    team_id=team.id,
                    thread_id=result.thread_id,
                    account_id=match.account_id,
                    defaults={
                        "account_external_id": match.account_external_id,
                        "match_source": match.match_source,
                    },
                )
    return result
