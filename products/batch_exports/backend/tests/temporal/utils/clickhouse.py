import asyncio
import collections.abc

import aiohttp.client_exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from posthog.clickhouse.managed_schema import ClickHouseDatabase
from posthog.temporal.common.asyncpa import InvalidMessageFormat
from posthog.temporal.common.clickhouse import ClickHouseClient, ClickHouseError

from products.batch_exports.backend.temporal.pipeline.producer import slice_record_batch


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
    # The Kafka tables and their materialized views are not part of the default test schema.
    await asyncio.to_thread(ClickHouseDatabase().apply_schema, kafka=True)


EVENTS_TABLES = (
    "sharded_events",
    "sharded_events_json",
    "distributed_events_recent",
    "events_recent",
    "sharded_events_recent",
)
PERSONS_TABLES = ("person_distinct_id2", "person")
SESSIONS_TABLES = ("sharded_raw_sessions", "raw_sessions")


async def truncate_tables(clickhouse_client, tables: collections.abc.Iterable[str]) -> None:
    async with asyncio.TaskGroup() as tg:
        for table in tables:
            tg.create_task(execute_query(clickhouse_client, f"TRUNCATE TABLE IF EXISTS {table}"))


async def truncate_events(clickhouse_client):
    await truncate_tables(clickhouse_client, EVENTS_TABLES)


async def truncate_persons(clickhouse_client):
    await truncate_tables(clickhouse_client, PERSONS_TABLES)


async def truncate_sessions(clickhouse_client):
    await truncate_tables(clickhouse_client, SESSIONS_TABLES)


async def truncate_all(clickhouse_client):
    await truncate_tables(clickhouse_client, EVENTS_TABLES + PERSONS_TABLES + SESSIONS_TABLES)


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
