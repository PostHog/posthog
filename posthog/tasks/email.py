import uuid
from datetime import datetime
from typing import List, Optional

import posthoganalytics
import structlog
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone

from posthog.celery import app
from posthog.email import EmailMessage, is_email_available
from posthog.event_usage import report_first_ingestion_reminder_email_sent, report_second_ingestion_reminder_email_sent
from posthog.models import Organization, OrganizationInvite, OrganizationMembership, Plugin, PluginConfig, Team, User

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
            "expiry_date": (timezone.now() + timezone.timedelta(days=3)).strftime("%b %d %Y"),
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
def send_password_reset(user_id: int) -> None:
    user = User.objects.get(pk=user_id)
    token = default_token_generator.make_token(user)
    message = EmailMessage(
        campaign_key=f"password-reset-{user.uuid}-{timezone.now().timestamp()}",
        subject=f"Reset your PostHog password",
        template_name="password_reset",
        template_context={
            "preheader": "Please follow the link inside to reset your password.",
            "link": f"/reset/{user.uuid}/{token}",
            "cloud": settings.MULTI_TENANCY,
            "site_url": settings.SITE_URL,
            "social_providers": list(user.social_auth.values_list("provider", flat=True)),
        },
    )
    message.add_recipient(user.email)
    message.send()


@app.task(max_retries=1)
def send_fatal_plugin_error(
    plugin_config_id: int, plugin_config_updated_at: Optional[str], error: str, is_system_error: bool
) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    plugin_config: PluginConfig = PluginConfig.objects.select_related("plugin", "team").get(id=plugin_config_id)
    plugin: Plugin = plugin_config.plugin
    team: Team = plugin_config.team
    campaign_key: str = f"plugin_disabled_email_plugin_config_{plugin_config_id}_updated_at_{plugin_config_updated_at}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"[Alert] {plugin} has been disabled in project {team} due to a fatal error",
        template_name="fatal_plugin_error",
        template_context={"plugin": plugin, "team": team, "error": error, "is_system_error": is_system_error},
    )
    memberships_to_email = [
        membership
        for membership in OrganizationMembership.objects.select_related("user", "organization").filter(
            organization_id=team.organization_id
        )
        # Only send the email to users who have access to the affected project
        # Those without access have `effective_membership_level` of `None`
        if team.get_effective_membership_level_for_parent_membership(membership) is not None
    ]
    if memberships_to_email:
        for membership in memberships_to_email:
            message.add_recipient(email=membership.user.email, name=membership.user.first_name)
        message.send(send_async=False)


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


def get_users_for_orgs_with_no_ingested_events(org_created_from: datetime, org_created_to: datetime) -> List[User]:
    # Get all users for organization that haven't ingested any events
    users = []
    recently_created_organizations = Organization.objects.filter(
        created_at__gte=org_created_from, created_at__lte=org_created_to,
    )

    for organization in recently_created_organizations:
        orgs_teams = Team.objects.filter(organization=organization)
        have_ingested = orgs_teams.filter(ingested_event=True).exists()
        if not have_ingested:
            users.extend(organization.members.all())
    return users


@app.task(max_retries=1)
def send_first_ingestion_reminder_emails() -> None:
    if is_email_available():
        one_day_ago = timezone.now() - timezone.timedelta(days=1)
        two_days_ago = timezone.now() - timezone.timedelta(days=2)
        users_to_email = get_users_for_orgs_with_no_ingested_events(
            org_created_from=two_days_ago, org_created_to=one_day_ago
        )

        campaign_key = "first_ingestion_reminder"

        for user in users_to_email:
            if posthoganalytics.feature_enabled("re-engagement-emails", user.distinct_id):
                message = EmailMessage(
                    campaign_key=campaign_key,
                    subject="Get started: How to send events to PostHog",
                    reply_to="hey@posthog.com",
                    template_name="first_ingestion_reminder",
                    template_context={"first_name": user.first_name},
                )

                message.add_recipient(user.email)
                message.send()
                report_first_ingestion_reminder_email_sent(user)


@app.task(max_retries=1)
def send_second_ingestion_reminder_emails() -> None:
    if is_email_available():
        four_days_ago = timezone.now() - timezone.timedelta(days=4)
        five_days_ago = timezone.now() - timezone.timedelta(days=5)
        users_to_email = get_users_for_orgs_with_no_ingested_events(
            org_created_from=five_days_ago, org_created_to=four_days_ago
        )

        campaign_key = "second_ingestion_reminder"

        for user in users_to_email:
            if posthoganalytics.feature_enabled("re-engagement-emails", user.distinct_id):
                message = EmailMessage(
                    campaign_key=campaign_key,
                    subject="Your PostHog project is waiting for events",
                    reply_to="hey@posthog.com",
                    template_name="second_ingestion_reminder",
                    template_context={"first_name": user.first_name},
                )

                message.add_recipient(user.email)
                message.send()
                report_second_ingestion_reminder_email_sent(user)
