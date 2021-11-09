import datetime
import logging
from typing import Optional

from posthog.celery import app
from posthog.email import EmailMessage, is_email_available
from posthog.models import Event, Organization, OrganizationInvite, PersonDistinctId, Team, User, organization
from posthog.templatetags.posthog_filters import compact_number
from posthog.utils import get_previous_week

logger = logging.getLogger(__name__)


def send_weekly_email_reports() -> None:
    """
    Schedules an async task to send the weekly email report for each team.
    """

    if not is_email_available():
        logger.info("Skipping send_weekly_email_report because email is not properly configured")
        return

    for team in Team.objects.order_by("pk"):
        _send_weekly_email_report_for_team.delay(team_id=team.pk)


@app.task(ignore_result=True, max_retries=1)
def _send_weekly_email_report_for_team(team_id: int) -> None:
    """
    Sends the weekly email report to all users in a team.
    """

    period_start, period_end = get_previous_week()
    last_week_start: datetime.datetime = period_start - datetime.timedelta(7)
    last_week_end: datetime.datetime = period_end - datetime.timedelta(7)

    campaign_key: str = f"weekly_report_for_team_{team_id}_on_{period_start.strftime('%Y-%m-%d')}"

    team = Team.objects.get(pk=team_id)

    event_data_set = Event.objects.filter(team=team, timestamp__gte=period_start, timestamp__lte=period_end,)

    active_users = PersonDistinctId.objects.filter(
        distinct_id__in=event_data_set.values("distinct_id").distinct(),
    ).distinct()
    active_users_count: int = active_users.count()

    if active_users_count == 0:
        # TODO: Send an email prompting fix to no active users
        return

    last_week_users = PersonDistinctId.objects.filter(
        distinct_id__in=Event.objects.filter(team=team, timestamp__gte=last_week_start, timestamp__lte=last_week_end,)
        .values("distinct_id")
        .distinct(),
    ).distinct()
    last_week_users_count: int = last_week_users.count()

    two_weeks_ago_users = PersonDistinctId.objects.filter(
        distinct_id__in=Event.objects.filter(
            team=team,
            timestamp__gte=last_week_start - datetime.timedelta(7),
            timestamp__lte=last_week_end - datetime.timedelta(7),
        )
        .values("distinct_id")
        .distinct(),
    ).distinct()  # used to compute delta in churned users
    two_weeks_ago_users_count: int = two_weeks_ago_users.count()

    not_last_week_users = PersonDistinctId.objects.filter(
        pk__in=active_users.difference(last_week_users,).values_list("pk", flat=True,)
    )  # users that were present this week but not last week

    churned_count = last_week_users.difference(active_users).count()
    churned_ratio: Optional[float] = (churned_count / last_week_users_count if last_week_users_count > 0 else None)
    last_week_churn_ratio: Optional[float] = (
        two_weeks_ago_users.difference(last_week_users).count() / two_weeks_ago_users_count
        if two_weeks_ago_users_count > 0
        else None
    )
    churned_delta: Optional[float] = (
        churned_ratio / last_week_churn_ratio - 1 if last_week_churn_ratio else None  # type: ignore
    )

    message = EmailMessage(
        campaign_key=campaign_key,
        subject=f"PostHog weekly report for {period_start.strftime('%b %d, %Y')} to {period_end.strftime('%b %d')}",
        template_name="weekly_report",
        template_context={
            "preheader": f"Your PostHog weekly report is ready! Your team had {compact_number(active_users_count)} active users last week! 🎉",
            "team": team.name,
            "period_start": period_start,
            "period_end": period_end,
            "active_users": active_users_count,
            "active_users_delta": active_users_count / last_week_users_count - 1 if last_week_users_count > 0 else None,
            "user_distribution": {
                "new": not_last_week_users.filter(person__created_at__gte=period_start).count() / active_users_count,
                "retained": active_users.intersection(last_week_users).count() / active_users_count,
                "resurrected": not_last_week_users.filter(person__created_at__lt=period_start).count()
                / active_users_count,
            },
            "churned_users": {"abs": churned_count, "ratio": churned_ratio, "delta": churned_delta},
        },
    )

    for user in team.organization.members.all():
        # TODO: Skip "unsubscribed" users
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
        template_context={"invite": invite},
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
