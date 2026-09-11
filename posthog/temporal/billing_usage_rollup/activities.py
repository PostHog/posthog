import asyncio
from datetime import UTC, date, datetime, time, timedelta

import structlog
from temporalio import activity

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.usage_ingestion.billing_usage_records import (
    BILLING_USAGE_RECORDS_HOURLY_EXISTING_ROWS_SQL,
    BILLING_USAGE_RECORDS_HOURLY_ROLLUP_SQL,
)
from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput
from posthog.temporal.common.heartbeat import Heartbeater

logger = structlog.get_logger(__name__)


def rollup_billing_usage_records_day(day: date) -> None:
    day_start = datetime.combine(day, time.min, UTC)
    day_end = day_start + timedelta(days=1)
    parameters = {"day_start": day_start, "day_end": day_end}

    with tags_context(product=Product.BILLING, feature=Feature.BILLING_ETL, workload=Workload.OFFLINE.value):
        existing_rows = sync_execute(BILLING_USAGE_RECORDS_HOURLY_EXISTING_ROWS_SQL(), parameters)[0][0]
        if existing_rows:
            logger.warning(
                "reconciling_existing_billing_usage_rollup", day=day.isoformat(), existing_rows=existing_rows
            )
        sync_execute(
            BILLING_USAGE_RECORDS_HOURLY_ROLLUP_SQL(),
            {**parameters, "rolled_up_at": datetime.now(UTC)},
            workload=Workload.OFFLINE,
        )


@activity.defn(name="rollup-billing-usage-records")
async def rollup_billing_usage_records(input: BillingUsageRecordsRollupInput) -> None:
    day = date.fromisoformat(input.day)
    async with Heartbeater():
        await asyncio.to_thread(rollup_billing_usage_records_day, day)
    logger.info("rolled_up_billing_usage_records", day=day.isoformat())
