from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.email import EmailMessage
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.logic.customer_tasks import _visible_task_queryset
from products.customer_analytics.backend.models.customer_task import CustomerTaskStatus


@frozen
class CustomerTaskDigestItem:
    name: str
    url: str
    due_label: str
    account_name: str | None


@frozen
class CustomerTaskDigest:
    project_name: str
    due_today: tuple[CustomerTaskDigestItem, ...]
    due_this_week: tuple[CustomerTaskDigestItem, ...]
    overdue_count: int
    overdue_url: str
    due_today_url: str
    settings_url: str


def build_customer_task_digest(*, user: User, team: Team, reference_time: datetime) -> CustomerTaskDigest | None:
    if timezone.is_naive(reference_time):
        raise ValueError("reference_time must include a timezone")
    access = UserAccessControl(user=user, team=team)
    if not user.is_active or not access.check_access_level_for_object(team, required_level="member"):
        return None

    project_timezone = ZoneInfo(team.timezone)
    today = reference_time.astimezone(project_timezone).date()
    today_start = datetime.combine(today, time.min, tzinfo=project_timezone)
    tomorrow_start = datetime.combine(today + timedelta(days=1), time.min, tzinfo=project_timezone)
    weekend_start = datetime.combine(today + timedelta(days=5 - today.weekday()), time.min, tzinfo=project_timezone)
    tasks = _visible_task_queryset(team.id, access).filter(
        assigned_to_id=user.id,
        status__in=[CustomerTaskStatus.OPEN, CustomerTaskStatus.IN_PROGRESS],
        archived_at__isnull=True,
        due_at__isnull=False,
    )
    overdue_count = tasks.filter(due_at__lt=reference_time).count()
    tasks_url = f"{settings.SITE_URL}/project/{team.id}/customer_analytics/tasks"
    due_today: list[CustomerTaskDigestItem] = []
    due_this_week: list[CustomerTaskDigestItem] = []
    period_end = max(tomorrow_start, weekend_start)
    for task in tasks.filter(due_at__gte=today_start, due_at__lt=period_end).order_by("due_at", "id"):
        assert task.due_at is not None
        local_due = task.due_at.astimezone(project_timezone)
        item = CustomerTaskDigestItem(
            name=task.name,
            url=f"{tasks_url}?{urlencode({'task_id': str(task.id)})}",
            due_label=local_due.strftime("%a, %b %d at %H:%M %Z"),
            account_name=task.account.name if task.account else None,
        )
        if local_due.date() == today:
            due_today.append(item)
        else:
            due_this_week.append(item)

    if not due_today and not due_this_week and not overdue_count:
        return None
    return CustomerTaskDigest(
        project_name=team.name,
        due_today=tuple(due_today),
        due_this_week=tuple(due_this_week),
        overdue_count=overdue_count,
        overdue_url=f"{tasks_url}?{urlencode({'status': 'open', 'assignee': 'me', 'archive': 'active', 'due': 'overdue'})}",
        due_today_url=f"{tasks_url}?{urlencode({'status': 'open', 'assignee': user.id, 'archive': 'active', 'due': 'today'})}",
        settings_url=f"{settings.SITE_URL}/project/{team.id}/customer_analytics/configuration?tab=customer-analytics-event-stream",
    )


def build_customer_task_digest_email(*, digest: CustomerTaskDigest, user: User, campaign_key: str) -> EmailMessage:
    context = asdict(digest)
    context["due_today"] = list(context["due_today"])
    context["due_this_week"] = list(context["due_this_week"])
    message = EmailMessage(
        campaign_key=campaign_key,
        template_name="customer_task_digest",
        subject="Your customer tasks",
        template_context={"digest": context},
    )
    message.add_user_recipient(user)
    return message
