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
    def __init__(
        self,
        team_id: int,
        batch_exports: list[BatchExport],
        s3fs: fs.S3FileSystem,
    ):
        self.team_id = team_id
        self.s3fs = s3fs
        self.batch_exports = batch_exports
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

    def filter_batch_exports(
        self,
        deleted: bool | None = False,
        name: str | None = None,
        destination: str | None = None,
        paused: bool | None = None,
    ) -> list[BatchExport]:
        filters = {}
        if deleted is not None:
            filters["deleted"] = deleted

        if name is not None:
            filters["name"] = name

        if destination is not None:
            filters["destination__type"] = destination

        if paused is not None:
            filters["paused"] = paused

        self.batch_exports = list(
            BatchExport.objects.select_related("destination").filter(team_id=self.team_id, **filters)
        )
        return self.batch_exports

    @functools.singledispatchmethod
    def get_batch_export(self, batch_export: BatchExport | str | int | uuid.UUID) -> BatchExport:
        """Get a single batch export from loaded batch exports.

        Can pass a `BatchExport` instance (which will just be returned), a batch
        export id, a batch export name, or an index on `self.batch_exports`.
        """
        raise TypeError(f"Unsupported type for `batch_export`: '{type(batch_export)}'")

    @get_batch_export.register
    def _(self, batch_export: BatchExport) -> BatchExport:
        return batch_export

    @get_batch_export.register
    def _(self, batch_export: str) -> BatchExport:
        return next(be for be in self.batch_exports if str(be.id) == batch_export or be.name == batch_export)

    @get_batch_export.register
    def _(self, batch_export: uuid.UUID) -> BatchExport:
        return next(be for be in self.batch_exports if be.id == batch_export)

    @functools.singledispatchmethod
    def _(self, batch_export: int) -> collections.abc.Generator[BatchExportRun, None, None]:
        yield from BatchExportRun.objects.filter(batch_export=self.batch_exports[batch_export])

    def iter_runs(
        self,
        batch_export: BatchExport | str | int | uuid.UUID,
        status: str | list[str] | None = None,
        order_by: str = "last_updated_at",
        descending: bool = True,
    ) -> collections.abc.Generator[BatchExportRun, None, None]:
        """Iterate over batch export runs."""
        batch_export = self.get_batch_export(batch_export)
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

        yield from queryset.order_by(f"{sign}last_updated_at")

    def get_latest_run(
        self, batch_export: BatchExport | str | int | uuid.UUID, status: str | list[str] | None = None
    ) -> BatchExportRun:
        return next(self.iter_runs(batch_export, status, order_by="last_updated_at", descending=True))

    def iter_s3_files(self, batch_export_run: BatchExportRun) -> collections.abc.Generator[pa.Table, None, None]:
        folder = _get_s3_staging_folder(
            batch_export_run.batch_export.id,
            batch_export_run.data_interval_start.isoformat(),
            batch_export_run.data_interval_end.isoformat(),
        )
        file_selector = fs.FileSelector(
            base_dir=f"{settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET}/{folder}", recursive=True
        )

        for file_info in self.s3fs.get_file_info(file_selector):
            with self.s3fs.open_input_file(file_info.path) as f:
                reader = ipc.RecordBatchStreamReader(f)
                yield reader.read_all()

    def load_s3_files(self, batch_export_run: BatchExportRun) -> pa.Table:
        tables = list(self.iter_s3_files(batch_export_run))
        return pa.concat_tables(tables)

    def iter_data_from_clickhouse(
        self,
        batch_export_run: BatchExportRun,
    ) -> collections.abc.Generator[pa.Table, None, None]:
        include_events = batch_export_run.batch_export.destination.config["include_events"]
        exclude_events = batch_export_run.batch_export.destination.config["exclude_events"]
        parameters = {
            "include_events": include_events,
            "exclude_events": exclude_events,
        }
        team_id = batch_export_run.batch_export.team.id

        extra_query_parameters = {}
        filters = batch_export_run.batch_export.model.get("filters", None)

        if filters is not None and len(filters) > 0:
            filters_str, extra_query_parameters = compose_filters_clause(
                filters, team_id=team_id, values=extra_query_parameters
            )
        else:
            filters_str, extra_query_parameters = "", extra_query_parameters

        full_range = (batch_export_run.data_interval_start, batch_export_run.data_interval_end)
        is_backfill = batch_export_run.backfill is not None

        if batch_export_run.batch_export.model["name"] == "persons":
            if is_backfill and full_range[0] is None:
                query = SELECT_FROM_PERSONS_BACKFILL
            else:
                query = SELECT_FROM_PERSONS
        else:
            if parameters.get("exclude_events", exclude_events):
                parameters["exclude_events"] = list(parameters["exclude_events"])
            else:
                parameters["exclude_events"] = []

            if parameters.get("include_events", include_events):
                parameters["include_events"] = list(parameters["include_events"])
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

        parameters["team_id"] = team_id
        parameters = {**parameters, **extra_query_parameters}

        for record_batch in self.clickhouse_client.stream_query_as_arrow(query, query_parameters=parameters):
            yield pa.Table.from_batches((record_batch,))

        def load_data_from_clickhouse(
            self,
            batch_export_run: BatchExportRun,
            filters: list[dict[str, str | list[str]]] | None = None,
            **parameters,
        ) -> pa.Table:
            tables = list(self.iter_data_from_clickhouse(batch_export_run, filters, is_backfill, **parameters))
            return pa.concat_tables(tables)
