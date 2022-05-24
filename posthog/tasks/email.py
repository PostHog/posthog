import uuid
from datetime import timedelta, timezone

import structlog
from django.conf import settings

from posthog.celery import app
from posthog.email import EmailMessage, is_email_available
from posthog.models import Organization, OrganizationInvite, User
from posthog.models.team import Team

logger = structlog.get_logger(__name__)


def send_message_to_all_staff_users(message: EmailMessage) -> None:
    for user in User.objects.filter(is_active=True, is_staff=True):
        message.add_recipient(email=user.email, name=user.first_name)

    message.send()


@app.task(max_retries=1)
def send_invite(invite_id: str) -> None:
    campaign_key: str = f"invite_email_{invite_id}"
    invite: OrganizationInvite = OrganizationInvite.objects.select_related("created_by", "organization").get(
        id=invite_id
    )
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"{invite.created_by.first_name} invited you to join {invite.organization.name} on PostHog",
        template_name="invite",
        template_context={
            "invite": invite,
            "expiry_date": (invite.created_at + timedelta(days=3)).strftime("%b %d %Y"),
        },
        reply_to=invite.created_by.email if invite.created_by and invite.created_by.email else "",
    )
    message.add_recipient(email=invite.target_email)
    message.send()


@app.task(max_retries=1)
def send_member_join(invitee_uuid: str, organization_id: str) -> None:
    invitee: User = User.objects.get(uuid=invitee_uuid)
    organization: Organization = Organization.objects.get(id=organization_id)
    campaign_key: str = f"member_join_email_org_{organization_id}_user_{invitee_uuid}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"{invitee.first_name} joined you on PostHog",
        template_name="member_join",
        template_context={"invitee": invitee, "organization": organization},
    )
    # Don't send this email to the new member themselves
    members_to_email = organization.members.exclude(email=invitee.email)
    if members_to_email:
        for user in members_to_email:
            message.add_recipient(email=user.email, name=user.first_name)
        message.send()


@app.task(max_retries=1)
def send_canary_email(user_email: str) -> None:
    message = EmailMessage(
        campaign_key=f"canary_email_{uuid.uuid4()}",
        subject="This is a test email of your PostHog instance",
        template_name="canary_email",
        template_context={"site_url": settings.SITE_URL},
    )
    message.add_recipient(email=user_email)
    message.send()


@app.task(max_retries=1)
def send_async_migration_complete_email(migration_key: str, time: str) -> None:

    message = EmailMessage(
        campaign_key=f"async_migration_complete_{migration_key}",
        subject=f"Async migration {migration_key} completed",
        template_name="async_migration_status",
        template_context={
            "migration_status_update": f"Async migration {migration_key} completed successfully at {time}."
        },
    )

    send_message_to_all_staff_users(message)


@app.task(max_retries=1)
def send_async_migration_errored_email(migration_key: str, time: str, error: str) -> None:

    message = EmailMessage(
        campaign_key=f"async_migration_error_{migration_key}",
        subject=f"Async migration {migration_key} errored",
        template_name="async_migration_error",
        template_context={"migration_key": migration_key, "time": time, "error": error},
    )

    send_message_to_all_staff_users(message)


def get_org_users_with_no_ingested_events(org_created_from, org_created_to):
    # Get all users for organization that haven't ingested any events
    users = []
    recently_created_organization = Organization.object.filter(
        created_at__gte=org_created_from, created_at__lte=org_created_to,
    )

    for organization in recently_created_organization:
        orgs_teams = Team.objects.filter(organization=organization)
        have_ingested = orgs_teams.filter(ingested_event=True).exists()
        if not have_ingested:
            users.extend(organization.members.all())
    return users


@app.task(max_retries=1)
def send_first_ingestion_reminder_emails() -> None:
    if is_email_available():
        users_to_email = get_org_users_with_no_ingested_events(
            timezone.now() - timezone.timedelta(days=2), timezone.now() - timezone.timedelta(days=1)
        )

        campaign_key: str = f"first_ingestion_reminder_"

        for user in users_to_email:
            message = EmailMessage(
                campaign_key=campaign_key,
                subject=f"Ingestion reminder?",
                template_name="first_ingestion_reminder",
                template_context={"first_name": user.first_name},
            )

            message.add_recipient(user.email)
            message.send()


@app.task(max_retries=1)
def send_final_ingestion_reminder_emails() -> None:
    # list of ids from orgs created exactly on the day of 96 hours ago

    orgs = Organization.objects.filter(
        created_at__date=(timezone.now() - timezone.timedelta(days=5)).date()
    ).values_list("id", flat=True)
    teams = Team.objects.filter(organization_id__in=orgs, ingested_event=False).values_list("id", flat=True)
    # (datetime.now()-datetime.timedelta(days=38)

    users = User.objects.filter(
        date_joined__date=(timezone.now() - timezone.timedelta(days=4).date()), current_team_id__in=teams
    )

    campaign_key: str = f"final_ingestion_reminder_"

    for user in users:
        message = EmailMessage(
            campaign_key=campaign_key, subject=f"???", template_name="final_ingestion_reminder",  # TODO
        )

        message.add_recipient(user.email)
        message.send()
