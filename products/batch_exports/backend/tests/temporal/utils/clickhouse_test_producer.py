"""A record batch producer that reads ClickHouse directly, for use as a test reference.

Production batch exports read from the internal S3 staging area via
``temporal.pipeline.producer.Producer``. This producer instead queries ClickHouse directly
with the ``SELECT_FROM_*`` templates. Having this separate from the production producer
ensures that we can independently verify the pipeline's output.
"""

import uuid
import typing
import asyncio
import datetime as dt
import collections.abc

from django.conf import settings

from posthog.sync import database_sync_to_async
from posthog.temporal.common.clickhouse import get_client
from posthog.temporal.common.logger import get_write_only_logger

from products.batch_exports.backend.service import BackfillDetails, BatchExportField
from products.batch_exports.backend.temporal.filters import compose_filters_clause
from products.batch_exports.backend.temporal.pipeline.producer import slice_record_batch
from products.batch_exports.backend.temporal.pipeline.query_ranges import (
    is_5_min_batch_export,
    use_distributed_events_recent_table,
    wait_for_delta_past_data_interval_end,
)
from products.batch_exports.backend.temporal.queue import RecordBatchQueue
from products.batch_exports.backend.temporal.record_batch_model import RecordBatchModel
from products.batch_exports.backend.temporal.sql.events import (
    SELECT_FROM_DISTRIBUTED_EVENTS_RECENT,
    SELECT_FROM_EVENTS_VIEW,
    SELECT_FROM_EVENTS_VIEW_BACKFILL,
    SELECT_FROM_EVENTS_VIEW_RECENT,
    SELECT_FROM_EVENTS_VIEW_UNBOUNDED,
    SELECT_FROM_EVENTS_WORKFLOWS,
)
from products.batch_exports.backend.temporal.sql.persons import SELECT_FROM_PERSONS, SELECT_FROM_PERSONS_BACKFILL

LOGGER = get_write_only_logger(__name__)


def default_fields() -> list[BatchExportField]:
    """Return list of default batch export Fields."""
    return [
        BatchExportField(expression="uuid", alias="uuid"),
        BatchExportField(expression="team_id", alias="team_id"),
        BatchExportField(expression="timestamp", alias="timestamp"),
        BatchExportField(expression="_inserted_at", alias="_inserted_at"),
        BatchExportField(expression="created_at", alias="created_at"),
        BatchExportField(expression="event", alias="event"),
        BatchExportField(expression="properties", alias="properties"),
        BatchExportField(expression="distinct_id", alias="distinct_id"),
        BatchExportField(expression="set", alias="set"),
        BatchExportField(
            expression="set_once",
            alias="set_once",
        ),
    ]


class ClickHouseTestProducer:
    """Async producer used in batch exports tests, which reads from ClickHouse directly.

    This used to be the SPMC producer used in production batch exports before we switched over to
    the internal stage architecture.

    Attributes:
        clickhouse_client: ClickHouse client used to produce RecordBatches.
        _task: Used to keep track of producer background task.
    """

    def __init__(self, model: RecordBatchModel | None = None):
        self.model = model
        self.logger = LOGGER.bind()
        self._task: asyncio.Task | None = None

    @property
    def task(self) -> asyncio.Task:
        if self._task is None:
            raise ValueError("Producer task is not initialized, have you called `ClickHouseTestProducer.start()`?")
        return self._task

    async def start(
        self,
        queue: RecordBatchQueue,
        full_range: tuple[dt.datetime | None, dt.datetime],
        is_backfill: bool,
        backfill_details: BackfillDetails | None,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        **kwargs,
    ) -> asyncio.Task:
        """Dispatch to one of two implementations, depending on `self.model`."""
        if self.model is not None:
            return await self.start_with_model(
                queue=queue,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                full_range=full_range,
            )
        else:
            return await self.start_without_model(
                queue=queue,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                full_range=full_range,
                is_backfill=is_backfill,
                backfill_details=backfill_details,
                **kwargs,
            )

    async def start_with_model(
        self,
        queue: RecordBatchQueue,
        full_range: tuple[dt.datetime | None, dt.datetime],
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        assert self.model is not None

        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                query_or_model=self.model,
                full_range=full_range,
                queue=queue,
                query_parameters={},
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                team_id=self.model.team_id,
            ),
            name="record_batch_producer",
        )
        return self._task

    async def start_without_model(
        self,
        queue: RecordBatchQueue,
        model_name: str,
        # TODO: remove once all backfill inputs are migrated
        is_backfill: bool,
        backfill_details: BackfillDetails | None,
        team_id: int,
        full_range: tuple[dt.datetime | None, dt.datetime],
        fields: list[BatchExportField] | None = None,
        destination_default_fields: list[BatchExportField] | None = None,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
        filters: list[dict[str, str | list[str] | None]] | None = None,
        order_columns: collections.abc.Iterable[str] | None = ("_inserted_at", "event"),
        is_workflows: bool = False,
        **parameters,
    ) -> asyncio.Task:
        if fields is None:
            if destination_default_fields is None:
                fields = default_fields()
            else:
                fields = destination_default_fields

        extra_query_parameters = parameters.pop("extra_query_parameters", {}) or {}

        if filters is not None and len(filters) > 0:
            filters_str, extra_query_parameters = await database_sync_to_async(compose_filters_clause)(
                filters, team_id=team_id, values=extra_query_parameters
            )
        else:
            filters_str, extra_query_parameters = "", extra_query_parameters

        # TODO: this can be simplified once all backfill inputs are migrated
        is_backfill = (backfill_details is not None) or is_backfill

        if model_name == "persons":
            if is_backfill and full_range[0] is None:
                query = SELECT_FROM_PERSONS_BACKFILL
            else:
                query = SELECT_FROM_PERSONS
        else:
            if parameters.get("exclude_events", None):
                parameters["exclude_events"] = list(parameters["exclude_events"])
            else:
                parameters["exclude_events"] = []

            if parameters.get("include_events", None):
                parameters["include_events"] = list(parameters["include_events"])
            else:
                parameters["include_events"] = []

            # for 5 min batch exports we query the events_recent table, which is known to have zero replication lag, but
            # may not be able to handle the load from all batch exports
            if is_5_min_batch_export(full_range=full_range) and not is_backfill and not is_workflows:
                self.logger.debug("Using events_recent table for 5 min batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_RECENT
            # for other batch exports that should use `events_recent` we use the `distributed_events_recent` table
            # which is a distributed table that sits in front of the `events_recent` table
            elif (
                use_distributed_events_recent_table(
                    is_backfill=is_backfill, backfill_details=backfill_details, data_interval_start=full_range[0]
                )
                and not is_workflows
            ):
                self.logger.debug("Using distributed_events_recent table for batch export")
                query_template = SELECT_FROM_DISTRIBUTED_EVENTS_RECENT
            elif is_workflows:
                self.logger.debug("Using workflows events query for batch export")
                query_template = SELECT_FROM_EVENTS_WORKFLOWS
            elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
                self.logger.debug("Using events_batch_export_unbounded view for batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
            elif is_backfill:
                self.logger.debug("Using events_batch_export_backfill view for batch export")
                query_template = SELECT_FROM_EVENTS_VIEW_BACKFILL
            else:
                self.logger.debug("Using events_batch_export view for batch export")
                query_template = SELECT_FROM_EVENTS_VIEW
                lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(
                    team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS
                )
                parameters["lookback_days"] = lookback_days

            if "_inserted_at" not in [field["alias"] for field in fields]:
                control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
            else:
                control_fields = []

            query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

            if filters_str:
                filters_str = f"AND {filters_str}"

            if str(team_id) in settings.BATCH_EXPORT_ORDERLESS_TEAM_IDS or not order_columns:
                order = ""
            else:
                order = f"ORDER BY {','.join(order_columns)}"

            query = query_template.safe_substitute(fields=query_fields, filters=filters_str, order=order)

        parameters["team_id"] = team_id
        parameters = {**parameters, **extra_query_parameters}

        self._task = asyncio.create_task(
            self.produce_batch_export_record_batches_from_range(
                query_or_model=query,
                full_range=full_range,
                queue=queue,
                query_parameters=parameters,
                max_record_batch_size_bytes=max_record_batch_size_bytes,
                min_records_per_batch=min_records_per_batch,
                team_id=team_id,
            ),
            name="record_batch_producer",
        )

        return self.task

    async def produce_batch_export_record_batches_from_range(
        self,
        query_or_model: str | RecordBatchModel,
        full_range: tuple[dt.datetime | None, dt.datetime],
        queue: RecordBatchQueue,
        query_parameters: dict[str, typing.Any],
        team_id: int,
        max_record_batch_size_bytes: int = 0,
        min_records_per_batch: int = 100,
    ):
        """Produce Arrow record batches for a given date range into `queue`.

        Arguments:
            query: The ClickHouse query used to obtain record batches. The query should be have a
                `FORMAT ArrowStream` clause, although we do not enforce this.
            full_range: The full date range of record batches to produce.
            queue: The queue where to produce record batches.
            query_parameters: Additional query parameters.
            team_id: The team ID of the batch export.
            max_record_batch_size_bytes: The max size in bytes of a record batch to insert in `queue`.
                If a record batch is larger than this, `slice_record_batch` will be used to slice it
                into smaller record batches.
            min_records_batch_per_batch: If slicing a record batch, each slice should contain at least
                this number of records.
        """
        clickhouse_url = None
        # 5 min batch exports should query a single node, which is known to have zero replication lag
        if is_5_min_batch_export(full_range=full_range):
            clickhouse_url = settings.CLICKHOUSE_OFFLINE_5MIN_CLUSTER_HOST

        # Data can sometimes take a while to settle, so for 5 min batch exports we wait several seconds just to be safe.
        # For all other batch exports we wait for 1 minute since we're querying the events_recent table using a
        # distributed table and setting `max_replica_delay_for_distributed_queries` to 1 minute
        if is_5_min_batch_export(full_range):
            delta = dt.timedelta(seconds=30)
        else:
            delta = dt.timedelta(minutes=1)
        interval_start, interval_end = full_range
        await wait_for_delta_past_data_interval_end(interval_end, delta)

        async with get_client(team_id=team_id, clickhouse_url=clickhouse_url) as client:
            if not await client.is_alive():
                raise ConnectionError("Cannot establish connection to ClickHouse")

            if interval_start is not None:
                query_parameters["interval_start"] = interval_start.strftime("%Y-%m-%d %H:%M:%S.%f")
            query_parameters["interval_end"] = interval_end.strftime("%Y-%m-%d %H:%M:%S.%f")
            query_id = uuid.uuid4()
            self.logger.debug("Executing query with ID '%s'", query_id)

            if isinstance(query_or_model, RecordBatchModel):
                query, query_parameters = await query_or_model.as_query_with_parameters(interval_start, interval_end)
            else:
                query = query_or_model

            try:
                async for record_batch in client.astream_query_as_arrow(
                    query, query_parameters=query_parameters, query_id=str(query_id)
                ):
                    for record_batch_slice in slice_record_batch(
                        record_batch, max_record_batch_size_bytes, min_records_per_batch
                    ):
                        await queue.put(record_batch_slice)

            except Exception as e:
                self.logger.exception("Unexpected error occurred while producing record batches", exc_info=e)
                raise
