import asyncio

import aiohttp.client_exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from posthog.models.app_metrics2.sql import APP_METRICS2_DATA_TABLE_SQL, APP_METRICS2_MV_TABLE_SQL
from posthog.temporal.common.asyncpa import InvalidMessageFormat
from posthog.temporal.common.clickhouse import ClickHouseClient, ClickHouseError

from products.batch_exports.backend.temporal.spmc import slice_record_batch


@retry(
    retry=retry_if_exception_type(
        (aiohttp.client_exceptions.ClientOSError, aiohttp.client_exceptions.ServerDisconnectedError, ClickHouseError)
    ),
    # on attempts expired, raise the exception encountered in our code, not tenacity's retry error
    reraise=True,
    wait=wait_random_exponential(multiplier=0.2, max=3),
    stop=stop_after_attempt(3),
)
async def execute_query(clickhouse_client: ClickHouseClient, query: str, *data):
    """Try to prevent flakiness in CI by retrying the query if it fails."""
    return await clickhouse_client.execute_query(query, *data)


async def create_clickhouse_tables_and_views(clickhouse_client):
    from posthog.batch_exports.sql import (
        CREATE_EVENTS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
    )
    from posthog.clickhouse.schema import CREATE_KAFKA_TABLE_QUERIES, build_query

    create_view_queries = (
        CREATE_EVENTS_BATCH_EXPORT_VIEW,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_BACKFILL,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_UNBOUNDED,
        CREATE_EVENTS_BATCH_EXPORT_VIEW_RECENT,
        CREATE_PERSONS_BATCH_EXPORT_VIEW,
        CREATE_PERSONS_BATCH_EXPORT_VIEW_BACKFILL,
    )

    clickhouse_tasks = set()
    for query in create_view_queries + tuple(map(build_query, CREATE_KAFKA_TABLE_QUERIES)):
        task = asyncio.create_task(execute_query(clickhouse_client, query))
        clickhouse_tasks.add(task)
        task.add_done_callback(clickhouse_tasks.discard)

    done, pending = await asyncio.wait(clickhouse_tasks)

    if len(pending) > 0:
        raise ValueError("Not all required tables and views were created in time")

    for task in done:
        if exc := task.exception():
            raise exc

    for query in (
        APP_METRICS2_DATA_TABLE_SQL(),
        APP_METRICS2_MV_TABLE_SQL(),
    ):
        # NOTE: Must be executed in order and after Kafka tables
        await execute_query(clickhouse_client, query)

    return


async def truncate_events(clickhouse_client):
    await execute_query(clickhouse_client, "TRUNCATE TABLE IF EXISTS sharded_events")
    await execute_query(clickhouse_client, "TRUNCATE TABLE IF EXISTS events_recent")


async def truncate_persons(clickhouse_client):
    await execute_query(clickhouse_client, "TRUNCATE TABLE IF EXISTS person_distinct_id2")


async def truncate_sessions(clickhouse_client):
    await execute_query(clickhouse_client, "TRUNCATE TABLE IF EXISTS raw_sessions")


class FlakyClickHouseClient(ClickHouseClient):
    """Fake ClickHouseClient that simulates a failure after reading a certain number of records.

    Raises a `InvalidMessageFormat` exception after reading a certain number of records.
    This is an error we've seen in production.
    """

    def __init__(self, *args, fail_after_records, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_after_records = fail_after_records

    async def astream_query_as_arrow(self, *args, **kwargs):
        count = 0
        async for batch in super().astream_query_as_arrow(*args, **kwargs):
            # guarantees one record per batch
            for sliced_batch in slice_record_batch(batch, max_record_batch_size_bytes=1, min_records_per_batch=1):
                count += 1
                if count > self.fail_after_records:
                    raise InvalidMessageFormat("Simulated failure")
                yield sliced_batch
