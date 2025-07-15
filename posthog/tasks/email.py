import uuid
from datetime import datetime
from enum import Enum
from typing import Literal, Optional

import posthoganalytics
import structlog
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from posthog.batch_exports.models import BatchExportRun
from posthog.cloud_utils import is_cloud
from posthog.constants import INVITE_DAYS_VALIDITY
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
from posthog.models.error_tracking import ErrorTrackingIssueAssignment
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.utils import UUIDT
from posthog.user_permissions import UserPermissions

logger = structlog.get_logger(__name__)


class NotificationSetting(Enum):
    WEEKLY_PROJECT_DIGEST = "weekly_project_digest"
    PLUGIN_DISABLED = "plugin_disabled"
    ERROR_TRACKING_ISSUE_ASSIGNED = "error_tracking_issue_assigned"


NotificationSettingType = Literal["weekly_project_digest", "plugin_disabled", "error_tracking_issue_assigned"]


def send_message_to_all_staff_users(message: EmailMessage) -> None:
    for user in User.objects.filter(is_active=True, is_staff=True):
        message.add_recipient(email=user.email, name=user.first_name)

    message.send()


def get_members_to_notify(team: Team, notification_setting: NotificationSettingType) -> list[OrganizationMembership]:
    memberships_to_email = []
    memberships = OrganizationMembership.objects.prefetch_related("user", "organization").filter(
        organization_id=team.organization_id
    )
    for membership in memberships:
        if not membership.user.notification_settings.get(notification_setting, True):
            continue
        team_permissions = UserPermissions(membership.user).team(team)
        # Only send the email to users who have access to the affected project
        # Those without access have `effective_membership_level` of `None`
        if (
            team_permissions.effective_membership_level_for_parent_membership(membership.organization, membership)
            is not None
        ):
            memberships_to_email.append(membership)

    return memberships_to_email


def should_send_notification(
    user: User,
    notification_type: NotificationSettingType,
    team_id: Optional[int] = None,
) -> bool:
    """
    Determines if a notification should be sent to a user based on their notification settings.

    Args:
        user: The user to check settings for
        notification_type: The type of notification being sent. It must be the enum member's value!
        team_id: Optional team ID for team-specific notifications

    Returns:
        bool: True if the notification should be sent, False otherwise
    """
    settings = user.notification_settings

    if notification_type == NotificationSetting.WEEKLY_PROJECT_DIGEST.value:
        # First check global digest setting
        if settings.get("all_weekly_digest_disabled", False):
            return False

        # Then check project-specific setting if team_id provided
        if team_id is not None:
            project_settings = settings.get("project_weekly_digest_disabled", {})
            team_disabled = project_settings.get(str(team_id), False)
            return not team_disabled

        return True

    # Default to False (disabled) if not set
    elif notification_type == NotificationSetting.PLUGIN_DISABLED.value:
        return not settings.get(notification_type, True)

    # Default to True (enabled) if not set
    elif notification_type == NotificationSetting.ERROR_TRACKING_ISSUE_ASSIGNED.value:
        return settings.get(notification_type, True)

    # The below typeerror is ignored because we're currently handling the notification
    # types above, so technically it's unreachable. However if another is added but
    # not handled in this function, we want this as a fallback.
    return True  # type: ignore


@shared_task(**EMAIL_TASK_KWARGS)
def send_invite(invite_id: str) -> None:
    campaign_key: str = f"invite_email_{invite_id}"
    invite: OrganizationInvite = OrganizationInvite.objects.select_related("created_by", "organization").get(
        id=invite_id
    )
    message = EmailMessage(
        use_http=True,
        campaign_key=campaign_key,
        subject=f"{invite.created_by.first_name} invited you to join {invite.organization.name} on PostHog",
        template_name="invite",
        template_context={
            "invite": invite,
            "expiry_date": (timezone.now() + timezone.timedelta(days=INVITE_DAYS_VALIDITY)).strftime(
                "%B %d, %Y at %H:%M %Z"
            ),
            "inviter_first_name": invite.created_by.first_name if invite.created_by else "someone",
            "organization_name": invite.organization.name,
            "url": f"{settings.SITE_URL}/signup/{invite_id}",
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
        use_http=True,
        campaign_key=campaign_key,
        subject=f"{invitee.first_name} joined you on PostHog",
        template_name="member_join",
        template_context={
            "invitee": invitee,
            "organization": organization,
            "invitee_first_name": invitee.first_name,
            "organization_name": organization.name,
        },
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
        use_http=True,
        campaign_key=f"password-reset-{user.uuid}-{timezone.now().timestamp()}",
        subject=f"Reset your PostHog password",
        template_name="password_reset",
        template_context={
            "preheader": "Please follow the link inside to reset your password.",
            "link": f"/reset/{user.uuid}/{token}",
            "cloud": is_cloud(),
            "site_url": settings.SITE_URL,
            "social_providers": list(user.social_auth.values_list("provider", flat=True)),
            "url": f"{settings.SITE_URL}/reset/{user.uuid}/{token}",
        },
    )
    message.add_recipient(user.email)
    message.send(send_async=False)


@shared_task(**EMAIL_TASK_KWARGS)
def send_password_changed_email(user_id: int) -> None:
    user = User.objects.get(pk=user_id)
    message = EmailMessage(
        use_http=True,
        campaign_key=f"password-changed-{user.uuid}-{timezone.now().timestamp()}",
        subject="Your password has been changed",
        template_name="password_changed",
        template_context={
            "preheader": "Your password has been changed",
            "cloud": is_cloud(),
            "site_url": settings.SITE_URL,
        },
    )
    message.add_recipient(user.email)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_email_verification(user_id: int, token: str, next_url: str | None = None) -> None:
    user: User = User.objects.get(pk=user_id)
    message = EmailMessage(
        use_http=True,
        campaign_key=f"email-verification-{user.uuid}-{timezone.now().timestamp()}",
        subject=f"Verify your email address",
        template_name="email_verification",
        template_context={
            "preheader": "Please follow the link inside to verify your account.",
            "link": f"/verify_email/{user.uuid}/{token}{f'?next={next_url}' if next_url else ''}",
            "site_url": settings.SITE_URL,
            "url": f"{settings.SITE_URL}/verify_email/{user.uuid}/{token}{f'?next={next_url}' if next_url else ''}",
        },
    )
    message.add_recipient(user.pending_email if user.pending_email is not None else user.email)
    message.send(send_async=False)
    posthoganalytics.capture(
        distinct_id=user.distinct_id,
        event="verification email sent",
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

    memberships_to_email = get_members_to_notify(team, "plugin_disabled")
    if not memberships_to_email:
        return

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
    for membership in memberships_to_email:
        message.add_recipient(email=membership.user.email, name=membership.user.first_name)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_hog_function_disabled(hog_function_id: str) -> None:
    if not is_email_available(with_absolute_urls=True):
        return
    hog_function: HogFunction = HogFunction.objects.prefetch_related("team").get(id=hog_function_id)
    team = hog_function.team

    # We re-use the setting as it is the same from a user perspective
    memberships_to_email = get_members_to_notify(team, "plugin_disabled")
    if not memberships_to_email:
        return

    campaign_key: str = f"hog_function_disabled_{hog_function_id}_updated_at_{hog_function.updated_at.timestamp()}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"[Alert] Destination '{hog_function.name}' has been disabled in project '{team}' due to high error rate",
        template_name="hog_function_disabled",
        template_context={"hog_function": hog_function, "team": team},
    )
    for membership in memberships_to_email:
        message.add_recipient(email=membership.user.email, name=membership.user.first_name)
    message.send()


def send_batch_export_run_failure(
    batch_export_run_id: str | UUIDT,
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

    memberships_to_email = get_members_to_notify(team, "plugin_disabled")
    if not memberships_to_email:
        return

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

    for membership in memberships_to_email:
        message.add_recipient(email=membership.user.email, name=membership.user.first_name)
    message.send()


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
        use_http=True,
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
        use_http=True,
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
    message_old_address.send()
    message_new_address.send()


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


@shared_task(**EMAIL_TASK_KWARGS)
def send_two_factor_auth_enabled_email(user_id: int) -> None:
    user: User = User.objects.get(pk=user_id)
    message = EmailMessage(
        use_http=True,
        campaign_key=f"2fa_enabled_{user.uuid}-{timezone.now().timestamp()}",
        template_name="2fa_enabled",
        subject="You've enabled 2FA protection",
        template_context={
            "user_name": user.first_name,
            "user_email": user.email,
        },
    )
    message.add_recipient(user.email)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_two_factor_auth_disabled_email(user_id: int) -> None:
    user: User = User.objects.get(pk=user_id)
    message = EmailMessage(
        use_http=True,
        campaign_key=f"2fa_disabled_{user.uuid}-{timezone.now().timestamp()}",
        template_name="2fa_disabled",
        subject="You've disabled 2FA protection",
        template_context={
            "user_name": user.first_name,
            "user_email": user.email,
        },
    )
    message.add_recipient(user.email)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_two_factor_auth_backup_code_used_email(user_id: int) -> None:
    user: User = User.objects.get(pk=user_id)
    message = EmailMessage(
        use_http=True,
        campaign_key=f"2fa_backup_code_used_{user.uuid}-{timezone.now().timestamp()}",
        template_name="2fa_backup_code_used",
        subject="A backup code was used for your account",
        template_context={
            "user_name": user.first_name,
            "user_email": user.email,
        },
    )
    message.add_recipient(user.email)
    message.send()


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


def send_error_tracking_issue_assigned(assignment: ErrorTrackingIssueAssignment, assigner: User) -> None:
    if not is_email_available(with_absolute_urls=True):
        return

    team = assignment.issue.team
    memberships_to_email = get_members_to_notify(team, NotificationSetting.ERROR_TRACKING_ISSUE_ASSIGNED.value)
    if not memberships_to_email:
        return

    # Filter the memberships list to only include users assigned
    if assignment.user:
        memberships_to_email = [
            membership
            for membership in memberships_to_email
            if (membership.user == assignment.user and membership.user != assigner)
        ]
    elif assignment.role:
        role_users = assignment.role.members.all()
        memberships_to_email = [
            membership
            for membership in memberships_to_email
            if (membership.user in role_users and membership.user != assigner)
        ]

    campaign_key: str = f"error_tracking_issue_assigned_{assignment.id}_updated_at_{assignment.created_at.timestamp()}"
    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"[Issue]: {assignment.issue.name} assigned to you in project '{team}'",
        template_name="error_tracking_issue_assigned",
        template_context={
            "assigner": assigner,
            "assignment": assignment,
            "team": team,
            "site_url": settings.SITE_URL,
        },
    )
    for membership in memberships_to_email:
        message.add_recipient(email=membership.user.email, name=membership.user.first_name)
    message.send()


@shared_task(**EMAIL_TASK_KWARGS)
def send_hog_functions_digest_email(digest_data: dict) -> None:
    if not is_email_available(with_absolute_urls=True):
        return

    team_id = digest_data["team_id"]

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        logger.exception(f"Team {team_id} not found for HogFunctions digest email")
        return

    # Get members to email TODO: implement a new setting for this
    memberships_to_email = get_members_to_notify(team, "hog_functions_digest")
    if not memberships_to_email:
        return

    campaign_key = f"hog_functions_daily_digest_{team_id}_{digest_data['date_str']}"

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"Daily HogFunctions Digest for {team.name}",
        template_name="hog_functions_daily_digest",
        template_context={
            "team": team,
            "date": digest_data["formatted_date"],
            "functions": digest_data["functions"],
            "total_functions": digest_data["total_functions"],
            "total_succeeded": digest_data["total_succeeded"],
            "total_failed": digest_data["total_failed"],
            "total_filtered": digest_data["total_filtered"],
            "total_runs": digest_data["total_runs"],
            "site_url": settings.SITE_URL,
        },
    )

    for membership in memberships_to_email:
        message.add_recipient(email=membership.user.email, name=membership.user.first_name)

    message.send()
    logger.info(f"Sent HogFunctions digest email to team {team_id} with {digest_data['total_functions']} functions")


@shared_task(ignore_result=True)
def send_hog_functions_daily_digest() -> None:
    """
    Send daily digest email to teams with active HogFunctions & setting hog_functions_digest enabled
    Collects all metrics using ClickHouse aggregation and sends formatted data to email service.
    """
    from datetime import timedelta
    from posthog.clickhouse.client import sync_execute
    from posthog.models.hog_functions.hog_function import HogFunction

    logger.info("Starting HogFunctions daily digest task")

    # Calculate date range for yesterday's data
    yesterday = timezone.now() - timedelta(days=1)
    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    date_str = yesterday.strftime("%Y-%m-%d")
    formatted_date = yesterday.strftime("%B %d, %Y")

    # Get all teams with active, non-deleted HogFunctions from PostgreSQL
    teams_with_active_functions = (
        HogFunction.objects.filter(enabled=True, deleted=False).values_list("team_id", flat=True).distinct()
    )

    team_ids = list(teams_with_active_functions)
    logger.info(f"Found {len(team_ids)} teams with active HogFunctions")

    if not team_ids:
        logger.info("No teams with active HogFunctions found")
        return

    # Filter teams based on the feature flag setting
    allowed_team_ids = settings.HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS
    if allowed_team_ids:
        # Convert string team IDs to integers for comparison
        allowed_team_ids_int = [int(team_id) for team_id in allowed_team_ids]
        team_ids = [team_id for team_id in team_ids if team_id in allowed_team_ids_int]
        logger.info(f"Filtered to {len(team_ids)} teams based on HOG_FUNCTIONS_DAILY_DIGEST_TEAM_IDS setting")

        if not team_ids:
            logger.info("No teams in allowed list have active HogFunctions")
            return

    # Get HogFunction data from PostgreSQL
    hog_functions = HogFunction.objects.filter(team_id__in=team_ids, enabled=True, deleted=False).values(
        "id", "team_id", "name", "type"
    )

    if not hog_functions:
        logger.info("No active HogFunctions found for teams")
        return

    # Get metrics data from ClickHouse for these HogFunctions
    hog_function_ids = [str(hf["id"]) for hf in hog_functions]

    metrics_query = """
    SELECT
        team_id,
        app_source_id as hog_function_id,
        metric_name,
        sum(count) as total_count
    FROM app_metrics2
    WHERE team_id IN %(team_ids)s
    AND app_source = 'hog_function'
    AND app_source_id IN %(hog_function_ids)s
    AND timestamp >= %(start_time)s
    AND timestamp <= %(end_time)s
    AND metric_kind = 'other'
    GROUP BY team_id, app_source_id, metric_name
    ORDER BY team_id, app_source_id, metric_name
    """

    metrics_data = sync_execute(
        metrics_query,
        {
            "team_ids": team_ids,
            "hog_function_ids": hog_function_ids,
            "start_time": yesterday_start,
            "end_time": yesterday_end,
        },
    )

    # Group data by team and calculate all aggregations
    teams_data = {}

    # First, initialize all HogFunctions
    for hog_function in hog_functions:
        team_id = hog_function["team_id"]
        hog_function_id = str(hog_function["id"])

        if team_id not in teams_data:
            teams_data[team_id] = {}

        teams_data[team_id][hog_function_id] = {
            "id": hog_function_id,
            "name": hog_function["name"],
            "type": hog_function["type"],
            "metrics": {},
            "url": f"{settings.SITE_URL}/project/{team_id}/pipeline/destinations/{hog_function_id}",
        }

    # Then, add metrics data
    for row in metrics_data:
        team_id, hog_function_id, metric_name, count = row

        if team_id in teams_data and hog_function_id in teams_data[team_id]:
            teams_data[team_id][hog_function_id]["metrics"][metric_name] = count

    # Process each team's data and send emails
    for team_id, functions_data in teams_data.items():
        try:
            # Build function metrics with calculated totals
            function_metrics = []
            team_total_succeeded = 0
            team_total_failed = 0
            team_total_filtered = 0

            for function_data in functions_data.values():
                metrics = function_data["metrics"]
                succeeded = metrics.get("succeeded", 0)
                failed = metrics.get("failed", 0)
                filtered = metrics.get("filtered", 0)
                total_runs = succeeded + failed

                function_info = {
                    "id": function_data["id"],
                    "name": function_data["name"],
                    "type": function_data["type"],
                    "succeeded": succeeded,
                    "failed": failed,
                    "filtered": filtered,
                    "total_runs": total_runs,
                    "url": function_data["url"],
                }

                function_metrics.append(function_info)
                team_total_succeeded += succeeded
                team_total_failed += failed
                team_total_filtered += filtered

            # Only send email if there are functions with data
            if function_metrics:
                # Pre-calculate all totals and formatted data for email
                digest_data = {
                    "team_id": team_id,
                    "date_str": date_str,
                    "formatted_date": formatted_date,
                    "functions": function_metrics,
                    "total_functions": len(function_metrics),
                    "total_succeeded": team_total_succeeded,
                    "total_failed": team_total_failed,
                    "total_filtered": team_total_filtered,
                    "total_runs": team_total_succeeded + team_total_failed,
                }

                send_hog_functions_digest_email.delay(digest_data)
                logger.info(
                    f"Scheduled HogFunctions digest email for team {team_id} with {len(function_metrics)} functions"
                )

        except Exception as e:
            logger.exception(f"Failed to process HogFunctions digest for team {team_id}: {e}")

    logger.info("Completed HogFunctions daily digest task")
