import collections.abc
import functools
import uuid

import pyarrow as pa
import pyarrow.fs as fs
import pyarrow.ipc as ipc
from django.conf import settings
from django.db.models import Q

from posthog.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.temporal.batch_exports.bigquery_batch_export import bigquery_default_fields
from posthog.temporal.batch_exports.postgres_batch_export import postgres_default_fields
from posthog.temporal.batch_exports.pre_export_stage import _get_s3_staging_folder
from posthog.temporal.batch_exports.redshift_batch_export import redshift_default_fields
from posthog.temporal.batch_exports.s3_batch_export import s3_default_fields
from posthog.temporal.batch_exports.snowflake_batch_export import snowflake_default_fields
from posthog.temporal.batch_exports.spmc import (
    BatchExportField,
    compose_filters_clause,
    use_distributed_events_recent_table,
)
from posthog.temporal.batch_exports.sql import (
    SELECT_FROM_DISTRIBUTED_EVENTS_RECENT,
    SELECT_FROM_EVENTS_VIEW,
    SELECT_FROM_EVENTS_VIEW_BACKFILL,
    SELECT_FROM_EVENTS_VIEW_RECENT,
    SELECT_FROM_EVENTS_VIEW_UNBOUNDED,
    SELECT_FROM_PERSONS,
    SELECT_FROM_PERSONS_BACKFILL,
)
from posthog.temporal.common.clickhouse import ClickHouseClient


class BatchExportsDebugger:
    """Debugger for batch exports.

    This allows quick access to batch exports data and metadata for debugging.
    This debugger was designed with the following workflow in mind:

    1. Initialize the debugger with the ID of the team we are debugging.
    2. Inspect batch exports for the team in the `loaded_batch_exports`
       attribute.
    3. If we don't know which batch export we want to work with, we can
       narrow down the batch exports loaded by calling
       `load_batch_exports` and load a new (narrower) set of batch exports.
    4. If we know which batch export we want work with, set it by calling
       `BatchExportsDebugger.set_batch_export_from_loaded` with the ID, name,
       or index of the batch export. By default, the debugger will  the first
       batch export in `loaded_batch_exports`, so if you managed to narrow
       down `loaded_batch_exports` to just one, you don't need to set anything.
    5. We are done with the setup, and the next steps will depend on your
       specific debugging needs: Check the batch export latest run with
       `get_latest_run`, load the data for the run in the staging S3 bucket with
       `load_s3_files`, compare that with the data you get from ClickHouse using
       `load_data_from_clickhouse`.

    Attributes:
        team_id: The ID of the team we are debugging.
        batch_export: The working batch export we are debugging. An instance of
            the `BatchExport` Django model.
        loaded_batch_exports: The batch exports we have loaded for the team. The
            working batch export is by default the first loaded.
    """

    def __init__(
        self,
        team_id: int,
        initial_batch_export: BatchExport | None = None,
    ):
        if settings.TEST or settings.DEBUG:
            endpoint_url = settings.BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT
        else:
            endpoint_url = None

        self.team_id = team_id
        self.loaded_batch_exports = tuple(BatchExport.objects.filter(team_id=team_id))
        self._batch_export = initial_batch_export or None

        self.s3fs = fs.S3FileSystem(
            access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            secret_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            region=settings.BATCH_EXPORT_OBJECT_STORAGE_REGION,
            endpoint_override=endpoint_url,
        )
        self.clickhouse_client = ClickHouseClient(
            url=settings.CLICKHOUSE_OFFLINE_HTTP_URL,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE,
            max_execution_time=settings.CLICKHOUSE_MAX_EXECUTION_TIME,
            max_memory_usage=settings.CLICKHOUSE_MAX_MEMORY_USAGE,
            cancel_http_readonly_queries_on_client_close=1,
            output_format_arrow_string_as_string="true",
        )

    @property
    def batch_export(self) -> BatchExport:
        """Working batch export."""
        if self._batch_export is None:
            self._batch_export = self.loaded_batch_exports[0]

        assert self._batch_export is not None
        return self._batch_export

    def set_batch_export_from_loaded(self, batch_export: BatchExport | str | int | uuid.UUID | None = None) -> None:
        """Set working batch export from loaded batch exports.

        Multiple type parameters are allowed as described in `get_batch_export`.
        """
        self._batch_export = self.get_batch_export(batch_export)

    @functools.singledispatchmethod
    def get_batch_export(self, batch_export: BatchExport | str | int | uuid.UUID | None = None) -> BatchExport:
        """Get a single batch export from loaded batch exports.

        Can pass a `BatchExport` instance (which will just be returned), a batch
        export id, a batch export name, or an index on `self.batch_exports`. If
        nothing is passed, we return the first batch export in
        `self.batch_exports`, which is useful when we have already narrowed down
        to one batch export using `self.filter_batch_exports`.
        """
        if batch_export is None:
            return self.batch_export

        raise TypeError(f"Unsupported type for `batch_export`: '{type(batch_export)}'")

    @get_batch_export.register
    def _(self, batch_export: BatchExport) -> BatchExport:
        return batch_export

    @get_batch_export.register
    def _(self, batch_export: str) -> BatchExport:
        return next(be for be in self.loaded_batch_exports if str(be.id) == batch_export or be.name == batch_export)

    @get_batch_export.register
    def _(self, batch_export: uuid.UUID) -> BatchExport:
        return next(be for be in self.loaded_batch_exports if be.id == batch_export)

    @get_batch_export.register
    def _(self, batch_export: int) -> BatchExport:
        return self.loaded_batch_exports[batch_export]

    def load_batch_exports(
        self,
        id: str | None = None,
        deleted: bool | None = False,
        model: str | None = None,
        interval: str | None = None,
        name: str | None = None,
        destination: str | None = None,
        paused: bool | None = None,
    ) -> tuple[BatchExport, ...]:
        """Filter batch exports in the debugger context."""
        filters: dict[str, int | bool | str] = {}
        if deleted is not None:
            filters["deleted"] = deleted

        if model is not None:
            filters["model__iexact"] = model

        if interval is not None:
            filters["interval__iexact"] = interval

        if name is not None:
            filters["name"] = name

        if destination is not None:
            filters["destination__type__iexact"] = destination

        if paused is not None:
            filters["paused"] = paused

        if id is not None:
            filters["id"] = id

        self.loaded_batch_exports = tuple(
            BatchExport.objects.select_related("destination").filter(team_id=self.team_id, **filters)
        )
        return self.loaded_batch_exports

    def iter_runs(
        self,
        status: str | list[str] | None = None,
        order_by: str = "last_updated_at",
        descending: bool = True,
        offset: int = 0,
    ) -> collections.abc.Generator[BatchExportRun, None, None]:
        """Iterate over batch export runs."""
        batch_export = self.batch_export
        sign = "-" if descending else ""

        filters = {}
        query = None
        if isinstance(status, str):
            filters["status__iexact"] = status
        elif isinstance(status, list):
            query = Q()
            for s in status:
                query |= Q(status__iexact=s)

        queryset = BatchExportRun.objects.filter(batch_export=batch_export)

        if filters:
            queryset = queryset.filter(**filters)
        if query:
            queryset = queryset.filter(query)

        yield from queryset.order_by(f"{sign}{order_by}")[offset:]

    def get_latest_run(
        self,
        status: str | list[str] | None = None,
        offset: int = 0,
        order_by: str = "last_updated_at",
    ) -> BatchExportRun:
        """Get the latest run for a batch export.

        By default, we order runs by `last_updated_at`, but this can be modified.

        Examples:
            Get the latest updated run that failed:

            >>> bedbg = BatchExportsDebugger(team_id) # doctest: +SKIP
            >>> bedbg.get_latest_run(status="failed") # doctest: +SKIP
            <BatchExportRun: BatchExportRun object (...)>

            Get the latest created run:

            >>> bedbg = BatchExportsDebugger(team_id) # doctest: +SKIP
            >>> bedbg.get_latest_run(order_by="created_at") # doctest: +SKIP
            <BatchExportRun: BatchExportRun object (...)>
        """
        return next(self.iter_runs(status, order_by=order_by, descending=True, offset=offset))

    def iter_run_s3_data(self, batch_export_run: BatchExportRun) -> collections.abc.Generator[pa.Table, None, None]:
        folder = _get_s3_staging_folder(
            batch_export_run.batch_export.id,
            batch_export_run.data_interval_start.isoformat() if batch_export_run.data_interval_start else None,
            batch_export_run.data_interval_end.isoformat(),
        )
        file_selector = fs.FileSelector(
            base_dir=f"{settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET}/{folder}", recursive=True
        )

        for file_info in self.s3fs.get_file_info(file_selector):
            with self.s3fs.open_input_file(file_info.path) as f:
                reader = ipc.RecordBatchStreamReader(f)
                yield reader.read_all()

    def load_run_s3_data(self, batch_export_run: BatchExportRun) -> pa.Table:
        """Load data in S3 stage for a given batch export run."""
        tables = list(self.iter_run_s3_data(batch_export_run))
        return pa.concat_tables(tables)

    def iter_run_data_from_clickhouse(
        self,
        batch_export_run: BatchExportRun,
    ) -> collections.abc.Generator[pa.Table, None, None]:
        team_id = batch_export_run.batch_export.team.id
        full_range = (batch_export_run.data_interval_start, batch_export_run.data_interval_end)
        parameters = {"team_id": team_id, "interval_end": full_range[1].strftime("%Y-%m-%d %H:%M:%S.%f")}
        if full_range[0]:
            parameters["interval_start"] = full_range[0].strftime("%Y-%m-%d %H:%M:%S.%f")

        extra_query_parameters: dict[str, str] = {}
        filters = batch_export_run.batch_export.filters

        if filters is not None and len(filters) > 0:
            filters_str, extra_query_parameters = compose_filters_clause(
                filters, team_id=team_id, values=extra_query_parameters
            )
        else:
            filters_str, extra_query_parameters = "", extra_query_parameters

        is_backfill = batch_export_run.backfill is not None

        if batch_export_run.batch_export.model == BatchExport.Model.PERSONS:
            if is_backfill and full_range[0] is None:
                query = SELECT_FROM_PERSONS_BACKFILL
            else:
                query = SELECT_FROM_PERSONS
        else:
            if batch_export_run.batch_export.destination.config.get("exclude_events", None):
                parameters["exclude_events"] = list(batch_export_run.batch_export.destination.config["exclude_events"])
            else:
                parameters["exclude_events"] = []

            if batch_export_run.batch_export.destination.config.get("include_events", None):
                parameters["include_events"] = list(batch_export_run.batch_export.destination.config["include_events"])
            else:
                parameters["include_events"] = []

            # for 5 min batch exports we query the events_recent table, which is known to have zero replication lag, but
            # may not be able to handle the load from all batch exports
            if batch_export_run.batch_export.interval == "every 5 minutes" and not is_backfill:
                query_template = SELECT_FROM_EVENTS_VIEW_RECENT
            # for other batch exports that should use `events_recent` we use the `distributed_events_recent` table
            # which is a distributed table that sits in front of the `events_recent` table
            elif use_distributed_events_recent_table(
                is_backfill=is_backfill, backfill_details=None, data_interval_start=full_range[0]
            ):
                query_template = SELECT_FROM_DISTRIBUTED_EVENTS_RECENT
            elif str(team_id) in settings.UNCONSTRAINED_TIMESTAMP_TEAM_IDS:
                query_template = SELECT_FROM_EVENTS_VIEW_UNBOUNDED
            elif is_backfill:
                query_template = SELECT_FROM_EVENTS_VIEW_BACKFILL
            else:
                query_template = SELECT_FROM_EVENTS_VIEW
                lookback_days = settings.OVERRIDE_TIMESTAMP_TEAM_IDS.get(
                    team_id, settings.DEFAULT_TIMESTAMP_LOOKBACK_DAYS
                )
                parameters["lookback_days"] = lookback_days

            match batch_export_run.batch_export.destination.type:
                case BatchExportDestination.Destination.S3:
                    fields = s3_default_fields()
                case BatchExportDestination.Destination.SNOWFLAKE:
                    fields = snowflake_default_fields()
                case BatchExportDestination.Destination.BIGQUERY:
                    fields = bigquery_default_fields()
                case BatchExportDestination.Destination.POSTGRES:
                    fields = postgres_default_fields()
                case BatchExportDestination.Destination.REDSHIFT:
                    fields = redshift_default_fields()
                case t:
                    raise ValueError(f"Unsupported destination: {t}")

            if "_inserted_at" not in [field["alias"] for field in fields]:
                control_fields = [BatchExportField(expression="_inserted_at", alias="_inserted_at")]
            else:
                control_fields = []

            query_fields = ",".join(f"{field['expression']} AS {field['alias']}" for field in fields + control_fields)

            if filters_str:
                filters_str = f"AND {filters_str}"

            query = query_template.safe_substitute(fields=query_fields, filters=filters_str, order="")

        parameters = {**parameters, **extra_query_parameters}

        for record_batch in self.clickhouse_client.stream_query_as_arrow(query, query_parameters=parameters):
            yield pa.Table.from_batches((record_batch,))

    def load_run_data_from_clickhouse(
        self,
        batch_export_run: BatchExportRun,
    ) -> pa.Table:
        """Load data in ClickHouse for a given batch export run."""
        tables = list(self.iter_run_data_from_clickhouse(batch_export_run))
        return pa.concat_tables(tables)
