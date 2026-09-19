from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

import posthoganalytics

from posthog.email import (
    EmailDeliveryError,
    is_email_available,
    is_smtp_email_service_available,
    raise_if_delivery_rejected,
)
from posthog.models.messaging import MessagingRecord

from products.customer_analytics.backend.facade.contracts import TaskDigestPreferences
from products.customer_analytics.backend.logic.customer_task_digest import (
    build_customer_task_digest,
    build_customer_task_digest_email,
)
from products.customer_analytics.backend.logic.user_customer_analytics_config import read_task_digest
from products.customer_analytics.backend.metrics import record_task_digest_delivery
from products.customer_analytics.backend.models import UserCustomerAnalyticsConfig

TASK_DIGEST_FLAG = "customer-analytics-task-digest"
MAX_SEND_ATTEMPTS = 4


class TemporaryTaskDigestFailure(Exception):
    pass


def task_digest_scheduled_at(
    preferences: TaskDigestPreferences, project_timezone: str, now: datetime
) -> datetime | None:
    local_now = now.astimezone(ZoneInfo(project_timezone))
    if not preferences.enabled or (preferences.cadence == "weekdays" and local_now.weekday() >= 5):
        return None
    scheduled_at = datetime.combine(
        local_now.date(), time.fromisoformat(preferences.send_time), tzinfo=local_now.tzinfo
    ).astimezone(UTC)
    return scheduled_at if scheduled_at <= now else None


def task_digest_campaign_key(team_id: int, user_id: int, digest_date: date) -> str:
    return f"customer-task-digest:{team_id}:{user_id}:{digest_date.isoformat()}"


def task_digest_enabled(config: UserCustomerAnalyticsConfig) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            TASK_DIGEST_FLAG,
            str(config.user.distinct_id),
            groups={"organization": str(config.team.organization_id)},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def deliver_task_digest(team_id: int, user_id: int, digest_date: str) -> None:
    now = timezone.now()
    config = (
        UserCustomerAnalyticsConfig.objects.for_team(team_id)
        .select_related("user", "team")
        .filter(user_id=user_id, user__is_active=True)
        .first()
    )
    if config is None or not task_digest_enabled(config):
        return
    preferences = read_task_digest(config)
    scheduled_at = task_digest_scheduled_at(preferences, config.team.timezone, now)
    local_date = now.astimezone(ZoneInfo(config.team.timezone)).date()
    if scheduled_at is None or local_date.isoformat() != digest_date:
        return
    campaign_key = task_digest_campaign_key(team_id, user_id, local_date)
    if MessagingRecord.objects.filter(campaign_key=campaign_key, sent_at__isnull=False).exists():
        return
    digest = build_customer_task_digest(user=config.user, team=config.team, reference_time=now)
    if digest is None or not task_digest_enabled(config):
        return

    outcome = "permanent_rejection"
    email_available = is_email_available(with_absolute_urls=True) and is_smtp_email_service_available()
    with transaction.atomic():
        record = MessagingRecord.objects.filter(campaign_key=campaign_key).first()
        if record is None:
            record, _ = MessagingRecord.objects.get_or_create(raw_email=config.user.email, campaign_key=campaign_key)
        record = MessagingRecord.objects.select_for_update().get(pk=record.pk)
        if (record.campaign_count or 0) >= MAX_SEND_ATTEMPTS or MessagingRecord.objects.filter(
            campaign_key=campaign_key, sent_at__isnull=False
        ).exists():
            return
        attempt = (record.campaign_count or 0) + 1
        record.campaign_count = MAX_SEND_ATTEMPTS
        record.save(update_fields=["campaign_count"])

    if not email_available:
        outcome = "missing_configuration"
    else:
        message = build_customer_task_digest_email(digest=digest, user=config.user, campaign_key=campaign_key)
        try:
            message.send(send_async=False, retry=False)
            raise_if_delivery_rejected(campaign_key, config.user.email)
        except EmailDeliveryError:
            pass
        except (ConnectionError, TimeoutError, OSError):
            MessagingRecord.objects.filter(pk=record.pk, sent_at__isnull=True).update(campaign_count=attempt)
            outcome = "temporary_failure" if attempt < MAX_SEND_ATTEMPTS else "retries_exhausted"
        else:
            MessagingRecord.objects.filter(pk=record.pk, sent_at__isnull=False).update(campaign_count=attempt)
            outcome = "accepted"
    record_task_digest_delivery(
        outcome=outcome,
        delay_seconds=max(0, (timezone.now() - scheduled_at).total_seconds()) if outcome == "accepted" else None,
    )
    if outcome == "temporary_failure":
        raise TemporaryTaskDigestFailure()
