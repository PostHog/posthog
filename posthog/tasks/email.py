import uuid
from datetime import datetime
from typing import Optional

import posthoganalytics
import structlog
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from posthog.batch_exports.models import BatchExportRun
from posthog.cloud_utils import is_cloud
from posthog.email import EMAIL_TASK_KWARGS, EmailMessage, is_email_available
from posthog.models import (
    Organization,
    OrganizationInvite,
    OrganizationMembership,
    Plugin,
    PluginConfig,
    Team,
    User,
)
from posthog.user_permissions import UserPermissions

logger = structlog.get_logger(__name__)


def send_message_to_all_staff_users(message: EmailMessage) -> None:
    for user in User.objects.filter(is_active=True, is_staff=True):
        message.add_recipient(email=user.email, name=user.first_name)

    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
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


@shared_task(**EMAIL_TASK_KWARGS)
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


@shared_task(**EMAIL_TASK_KWARGS)
def send_password_reset(user_id: int, token: str) -> None:
    user = User.objects.get(pk=user_id)
    message = EmailMessage(
        campaign_key=f"password-reset-{user.uuid}-{timezone.now().timestamp()}",
        subject=f"Reset your PostHog password",
        template_name="password_reset",
        template_context={
            "preheader": "Please follow the link inside to reset your password.",
            "link": f"/reset/{user.uuid}/{token}",
            "cloud": is_cloud(),
            "site_url": settings.SITE_URL,
            "social_providers": list(user.social_auth.values_list("provider", flat=True)),
        },
    )
    message.add_recipient(user.email)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_email_verification(user_id: int, token: str) -> None:
    user: User = User.objects.get(pk=user_id)
    message = EmailMessage(
        campaign_key=f"email-verification-{user.uuid}-{timezone.now().timestamp()}",
        subject=f"Verify your email address",
        template_name="email_verification",
        template_context={
            "preheader": "Please follow the link inside to verify your account.",
            "link": f"/verify_email/{user.uuid}/{token}",
            "site_url": settings.SITE_URL,
        },
    )
    message.add_recipient(user.pending_email if user.pending_email is not None else user.email)
    message.send(send_async=False)
    posthoganalytics.capture(
        user.distinct_id,
        "verification email sent",
        groups={"organization": str(user.current_organization.id)},  # type: ignore
    )


@shared_task(**EMAIL_TASK_KWARGS)
def send_fatal_plugin_error(
    plugin_config_id: int,
    plugin_config_updated_at: Optional[str],
    error: str,
    is_system_error: bool,
) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    plugin_config: PluginConfig = PluginConfig.objects.prefetch_related("plugin", "team").get(id=plugin_config_id)
    plugin: Plugin = plugin_config.plugin
    team: Team = plugin_config.team
    campaign_key: str = f"plugin_disabled_email_plugin_config_{plugin_config_id}_updated_at_{plugin_config_updated_at}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"[Alert] {plugin} has been disabled in project {team} due to a fatal error",
        template_name="fatal_plugin_error",
        template_context={
            "plugin": plugin,
            "team": team,
            "error": error,
            "is_system_error": is_system_error,
        },
    )
    memberships_to_email = []
    memberships = OrganizationMembership.objects.prefetch_related("user", "organization").filter(
        organization_id=team.organization_id
    )
    for membership in memberships:
        if not membership.user.notification_settings["plugin_disabled"]:
            continue
        team_permissions = UserPermissions(membership.user).team(team)
        # Only send the email to users who have access to the affected project
        # Those without access have `effective_membership_level` of `None`
        if (
            team_permissions.effective_membership_level_for_parent_membership(membership.organization, membership)
            is not None
        ):
            memberships_to_email.append(membership)

    if memberships_to_email:
        for membership in memberships_to_email:
            message.add_recipient(email=membership.user.email, name=membership.user.first_name)
        message.send(send_async=False)


def send_batch_export_run_failure(
    batch_export_run_id: str,
) -> None:
    logger = structlog.get_logger(__name__)

    is_email_available_result = is_email_available(with_absolute_urls=True)
    if not is_email_available_result:
        logger.warning("Email service is not available")
        return None

    batch_export_run: BatchExportRun = BatchExportRun.objects.select_related("batch_export__team").get(
        id=batch_export_run_id
    )
    team: Team = batch_export_run.batch_export.team
    logger = logger.bind(team_id=team.id, batch_export_id=batch_export_run.batch_export.id)

    logger.info("Preparing notification email for batch export run %s", batch_export_run_id)

    # NOTE: We are taking only the date component to cap the number of emails at one per day per batch export.
    last_updated_at_date = batch_export_run.last_updated_at.strftime("%Y-%m-%d")

    campaign_key: str = (
        f"batch_export_run_email_batch_export_{batch_export_run.batch_export.id}_last_updated_at_{last_updated_at_date}"
    )

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog: {batch_export_run.batch_export.name} batch export run failure",
        template_name="batch_export_run_failure",
        template_context={
            "time": batch_export_run.last_updated_at.strftime("%I:%M%p %Z on %B %d"),
            "team": team,
            "id": batch_export_run.batch_export.id,
            "name": batch_export_run.batch_export.name,
        },
    )
    logger.info("Prepared notification email for campaign %s", campaign_key)

    memberships_to_email = []
    memberships = OrganizationMembership.objects.select_related("user", "organization").filter(
        organization_id=team.organization_id
    )

    for membership in memberships:
        has_notification_settings_enabled = membership.user.notification_settings.get("batch_export_run_failure", True)

        if has_notification_settings_enabled is False:
            logger.warning("User doesn't have batch export notifications enabled")
            continue

        team_permissions = UserPermissions(membership.user).team(team)
        # Only send the email to users who have access to the affected project
        # Those without access have `effective_membership_level` of `None`
        if (
            team_permissions.effective_membership_level_for_parent_membership(membership.organization, membership)
            is not None
        ):
            memberships_to_email.append(membership)

    if memberships_to_email:
        logger.info("Sending failure notification email")

        for membership in memberships_to_email:
            message.add_recipient(email=membership.user.email, name=membership.user.first_name)
        message.send(send_async=False)
    else:
        logger.info("No available recipients for notification email")


@shared_task(**EMAIL_TASK_KWARGS)
def send_canary_email(user_email: str) -> None:
    message = EmailMessage(
        campaign_key=f"canary_email_{uuid.uuid4()}",
        subject="This is a test email of your PostHog instance",
        template_name="canary_email",
        template_context={"site_url": settings.SITE_URL},
    )
    message.add_recipient(email=user_email)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_email_change_emails(now_iso: str, user_name: str, old_address: str, new_address: str) -> None:
    message_old_address = EmailMessage(
        campaign_key=f"email_change_old_address_{now_iso}",
        subject="This is no longer your PostHog account email",
        template_name="email_change_old_address",
        template_context={
            "user_name": user_name,
            "old_address": old_address,
            "new_address": new_address,
        },
    )
    message_new_address = EmailMessage(
        campaign_key=f"email_change_new_address_{now_iso}",
        subject="This is your new PostHog account email",
        template_name="email_change_new_address",
        template_context={
            "user_name": user_name,
            "old_address": old_address,
            "new_address": new_address,
        },
    )
    message_old_address.add_recipient(email=old_address)
    message_new_address.add_recipient(email=new_address)
    message_old_address.send(send_async=False)
    message_new_address.send(send_async=False)


@shared_task(**EMAIL_TASK_KWARGS)
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


@shared_task(**EMAIL_TASK_KWARGS)
def send_async_migration_errored_email(migration_key: str, time: str, error: str) -> None:
    message = EmailMessage(
        campaign_key=f"async_migration_error_{migration_key}",
        subject=f"Async migration {migration_key} errored",
        template_name="async_migration_error",
        template_context={"migration_key": migration_key, "time": time, "error": error},
    )

    send_message_to_all_staff_users(message)


def get_users_for_orgs_with_no_ingested_events(org_created_from: datetime, org_created_to: datetime) -> list[User]:
    # Get all users for organization that haven't ingested any events
    users = []
    recently_created_organizations = Organization.objects.filter(
        created_at__gte=org_created_from, created_at__lte=org_created_to
    )

    for organization in recently_created_organizations:
        orgs_teams = Team.objects.filter(organization=organization)
        have_ingested = orgs_teams.filter(ingested_event=True).exists()
        if not have_ingested:
            users.extend(organization.members.all())
    return users
