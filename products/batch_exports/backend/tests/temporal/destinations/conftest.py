import asyncio

import pytest

import aiohttp.client_exceptions
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from posthog.models.app_metrics2.sql import APP_METRICS2_DATA_TABLE_SQL, APP_METRICS2_MV_TABLE_SQL
from posthog.temporal.common.clickhouse import ClickHouseClient


@retry(
    retry=retry_if_exception_type(
        (aiohttp.client_exceptions.ClientOSError, aiohttp.client_exceptions.ServerDisconnectedError)
    ),
    # on attempts expired, raise the exception encountered in our code, not tenacity's retry error
    reraise=True,
    wait=wait_random_exponential(multiplier=0.2, max=3),
    stop=stop_after_attempt(3),
)
async def execute_query(query: str, clickhouse_client: ClickHouseClient):
    """Try to prevent flakiness in CI by retrying the query if it fails."""
    return await clickhouse_client.execute_query(query)


@pytest.fixture(scope="module", autouse=True)
async def create_clickhouse_tables_and_views(clickhouse_client, django_db_setup):
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
        task = asyncio.create_task(execute_query(query, clickhouse_client))
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
        await execute_query(query, clickhouse_client)

    return


@pytest.fixture(autouse=True)
async def truncate_events(clickhouse_client):
    """Fixture to automatically truncate sharded_events after a test.

    This is useful if during the test setup we insert a lot of events we wish to clean-up.
    """
    yield
    await execute_query("TRUNCATE TABLE IF EXISTS sharded_events", clickhouse_client)
    await execute_query("TRUNCATE TABLE IF EXISTS events_recent", clickhouse_client)


@pytest.fixture(autouse=True)
async def truncate_persons(clickhouse_client):
    """Fixture to automatically truncate person and person_distinct_id2 after a test.

    This is useful if during the test setup we insert a lot of persons we wish to clean-up.
    """
    yield
    await execute_query("TRUNCATE TABLE IF EXISTS person", clickhouse_client)
    await execute_query("TRUNCATE TABLE IF EXISTS person_distinct_id2", clickhouse_client)


@pytest.fixture(autouse=True)
async def truncate_sessions(clickhouse_client):
    """Fixture to automatically truncate raw_sessions after a test.

    This is useful if during the test setup we insert a lot of sessions we wish to clean-up.
    """
    yield
    await execute_query("TRUNCATE TABLE IF EXISTS raw_sessions", clickhouse_client)
