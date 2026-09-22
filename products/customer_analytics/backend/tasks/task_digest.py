from zoneinfo import ZoneInfo

from django.utils import timezone

from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models.messaging import MessagingRecord

from products.customer_analytics.backend.logic.task_digest_delivery import (
    MAX_SEND_ATTEMPTS,
    TemporaryTaskDigestFailure,
    deliver_task_digest,
    task_digest_campaign_key,
    task_digest_enabled,
    task_digest_scheduled_at,
)
from products.customer_analytics.backend.logic.user_customer_analytics_config import read_task_digest
from products.customer_analytics.backend.models import UserCustomerAnalyticsConfig

DIGEST_SCHEDULE_BATCH_SIZE = 100


@shared_task(
    name="customer_analytics.send_task_digest",
    queue=CeleryQueue.EMAIL.value,
    ignore_result=True,
    autoretry_for=(TemporaryTaskDigestFailure,),
    retry_backoff=60,
    retry_backoff_max=900,
    retry_jitter=True,
    max_retries=MAX_SEND_ATTEMPTS - 1,
)
def send_task_digest(team_id: int, user_id: int, digest_date: str) -> None:
    deliver_task_digest(team_id, user_id, digest_date)


@shared_task(name="customer_analytics.schedule_task_digests", ignore_result=True)
def schedule_task_digests(cursor: str | None = None) -> None:
    now = timezone.now()
    configs = (
        UserCustomerAnalyticsConfig.objects.unscoped()
        .filter(properties__task_digest__enabled=True, user__is_active=True)
        .select_related("user", "team")
    )
    if cursor is not None:
        configs = configs.filter(pk__gt=cursor)
    batch = list(configs.order_by("pk")[:DIGEST_SCHEDULE_BATCH_SIZE])
    for config in batch:
        preferences = read_task_digest(config)
        if task_digest_scheduled_at(preferences, config.team.timezone, now) is None or not task_digest_enabled(config):
            continue
        digest_date = now.astimezone(ZoneInfo(config.team.timezone)).date()
        campaign_key = task_digest_campaign_key(config.team_id, config.user_id, digest_date)
        campaign_records = MessagingRecord.objects.filter(  # nosemgrep: celery-task-team-scope-audit - this global model has no team field, and the key embeds team_id
            campaign_key=campaign_key
        )
        if campaign_records.filter(sent_at__isnull=False).exists():
            continue
        record = campaign_records.first()
        if record is not None and (record.sent_at is not None or (record.campaign_count or 0) >= MAX_SEND_ATTEMPTS):
            continue
        send_task_digest.delay(config.team_id, config.user_id, digest_date.isoformat())
    if len(batch) == DIGEST_SCHEDULE_BATCH_SIZE:
        schedule_task_digests.delay(str(batch[-1].pk))
