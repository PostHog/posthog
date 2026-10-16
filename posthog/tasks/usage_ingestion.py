import os
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any

import structlog
from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.usage_ingestion.client import UsageRecord, report_usage, team_is_enabled

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def send_usage_records(records: list[dict[str, Any]], site: str) -> None:
    report_usage((UsageRecord(**record) for record in records), site=site)


def enqueue_usage_records(records: Iterable[UsageRecord], *, site: str) -> None:
    if not os.environ.get("USAGE_INGESTION_ADDR"):
        return
    enabled = [asdict(record) for record in records if team_is_enabled(record.team_id)]
    if not enabled:
        return
    try:
        # Preserve the request's identity and clock when the worker delivers it later.
        send_usage_records.delay(enabled, site)
    except Exception:
        logger.warning("usage_ingestion_enqueue_failed", site=site, records=len(enabled), exc_info=True)
