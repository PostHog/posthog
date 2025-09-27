import uuid
import typing
import asyncio
import contextlib
import collections.abc

import pytest

import aiohttp.client_exceptions
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from posthog.batch_exports.models import BatchExportRun
from posthog.batch_exports.service import create_batch_export_run
from posthog.models.app_metrics2.sql import APP_METRICS2_DATA_TABLE_SQL, APP_METRICS2_MV_TABLE_SQL
from posthog.temporal.common.asyncpa import InvalidMessageFormat
from posthog.temporal.common.clickhouse import ClickHouseClient

from products.batch_exports.backend.temporal.batch_exports import StartBatchExportRunInputs
from products.batch_exports.backend.temporal.spmc import slice_record_batch


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


async def truncate_events(clickhouse_client):
    await execute_query("TRUNCATE TABLE IF EXISTS sharded_events", clickhouse_client)
    await execute_query("TRUNCATE TABLE IF EXISTS events_recent", clickhouse_client)


async def truncate_persons(clickhouse_client):
    await execute_query("TRUNCATE TABLE IF EXISTS person_distinct_id2", clickhouse_client)


async def truncate_sessions(clickhouse_client):
    await execute_query("TRUNCATE TABLE IF EXISTS raw_sessions", clickhouse_client)


@activity.defn(name="start_batch_export_run")
async def mocked_start_batch_export_run(inputs: StartBatchExportRunInputs) -> str:
    """Create a run and return some count >0 to avoid early return."""
    run = await sync_to_async(create_batch_export_run)(
        batch_export_id=uuid.UUID(inputs.batch_export_id),
        data_interval_start=inputs.data_interval_start,
        data_interval_end=inputs.data_interval_end,
        status=BatchExportRun.Status.STARTING,
    )

    return str(run.id)


async def get_record_batch_from_queue(queue, produce_task):
    while not queue.empty() or not produce_task.done():
        try:
            record_batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            if produce_task.done():
                break
            else:
                await asyncio.sleep(0)
                continue

        return record_batch
    return None


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


def remove_duplicates_from_records(
    records: list[dict[str, typing.Any]], key: collections.abc.Sequence[str] | None = None
) -> list[dict[str, typing.Any]]:
    """Remove duplicates from a list of records.

    Used in batch exports testing when we expect a number of duplicates not known
    beforehand to be present in the results. Since we can't know how many duplicates
    there are, and which exact records will be duplicated, we remove them so that
    comparisons won't fail.
    """
    if not key:
        dedup_key: tuple[str, ...] = ("uuid",)
    else:
        dedup_key = tuple(key)

    seen = set()

    def is_record_seen(record: dict[str, typing.Any]) -> bool:
        nonlocal seen

        pk = tuple(record[k] for k in dedup_key)

        if pk in seen:
            return True

        seen.add(pk)
        return False

    inserted_records = [record for record in records if not is_record_seen(record)]

    return inserted_records


@contextlib.contextmanager
def fail_on_application_error():
    """Context manager to fail the test if an application error is raised.

    Tests typically fail if a WorkflowFailureError is raised, but the error traceback you get back is not very helpful
    as it just contains the traceback from within Temporal's own code.
    This context manager will parse the error and fail the test with a more helpful message and trackback from our own
    code, which helps debug the issue.
    """
    try:
        yield
    except WorkflowFailureError as e:
        # try to parse the root cause of the error in case it's an error from our own code
        if isinstance(e.cause, ActivityError):
            if isinstance(e.cause.cause, ApplicationError):
                message = e.cause.cause.message
                error_type = e.cause.cause.type
                failure = e.cause.cause.failure
                stack_trace = failure.stack_trace if failure else None

                detailed_error = (
                    f"Workflow failed with an ApplicationError:\n\n"
                    f"  Error: {message}\n\n"
                    f"  Error Type: {error_type}\n"
                )
                if stack_trace:
                    detailed_error += f"  Error Stack Trace: {stack_trace}\n"

                pytest.fail(detailed_error)
        # not an application error, re-raise (which will also cause the test to fail)
        raise
