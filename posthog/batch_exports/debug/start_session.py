import argparse
import datetime as dt
import os

import django
import IPython
import pyarrow as pa
import pyarrow.fs as fs
import pyarrow.ipc as ipc
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

# ruff: noqa: E402
from posthog.models import BatchExport, BatchExportDestination
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


def main():
    parser = make_parser()
    namespace = parser.parse_args()
    start_session(
        namespace.team_id,
        namespace.batch_export_id,
    )


def make_parser():
    parser = argparse.ArgumentParser(
        prog="Batch exports debug session", description="Enter a debug session for batch exports"
    )
    parser.add_argument("-t", "--team-id", required=True, type=int)
    parser.add_argument("-b", "--batch-export-id", required=False, type=str)

    return parser


def start_session(team_id: int, batch_export_id: str):
    if settings.TEST or settings.DEBUG:
        endpoint_url = "http://localhost:19000"
    else:
        endpoint_url = settings.BATCH_EXPORT_OBJECT_STORAGE_ENDPOINT

    s3fs = fs.S3FileSystem(
        access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        region=settings.BATCH_EXPORT_OBJECT_STORAGE_REGION,
        endpoint_override=endpoint_url,
    )

    if batch_export_id:
        batch_exports = [BatchExport.objects.select_related("destination").get(id=batch_export_id, team_id=team_id)]
    else:
        batch_exports = list(BatchExport.objects.select_related("destination").filter(team_id=team_id, deleted=False))

    IPython.embed(locals={"debug": BatchExportDebug(batch_exports, s3fs)})


class BatchExportDebug:
    def __init__(
        self,
        batch_exports: list[BatchExport],
        s3fs: fs.S3FileSystem,
    ):
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

    def load_s3_files(
        self, batch_export_id: str, data_interval_start: str | dt.datetime, data_interval_end: str | dt.datetime
    ) -> pa.Table:
        if isinstance(data_interval_start, dt.datetime):
            start = data_interval_start.isoformat()
        else:
            start = data_interval_start

        if isinstance(data_interval_end, dt.datetime):
            end = data_interval_end.isoformat()
        else:
            end = data_interval_end

        folder = _get_s3_staging_folder(batch_export_id, start, end)
        file_selector = fs.FileSelector(base_dir=folder, recursive=True)

        tables = []
        for file_info in self.s3fs.get_file_info(file_selector):
            with self.s3fs.open_input_file(file_info.path) as f:
                reader = ipc.RecordBatchStreamReader(f)
                tables.append(reader.read_all())

        return pa.concat_tables(tables)

    def load_data_from_clickhouse(
        self,
        batch_export_id: str,
        data_interval_start: str | dt.datetime,
        data_interval_end: str | dt.datetime,
        filters: list[dict[str, str | list[str]]] | None = None,
        is_backfill: bool = False,
        **parameters,
    ) -> pa.Table:
        batch_export = next(
            batch_export for batch_export in self.batch_exports if str(batch_export.id) == batch_export_id
        )
        include_events = batch_export.destination.config["include_events"]
        exclude_events = batch_export.destination.config["exclude_events"]
        team_id = batch_export.team.id
        if isinstance(data_interval_start, str):
            start = dt.datetime.fromisoformat(data_interval_start)
        else:
            start = data_interval_start

        if isinstance(data_interval_end, str):
            end = dt.datetime.fromisoformat(data_interval_end)
        else:
            end = data_interval_end

        extra_query_parameters = parameters.pop("extra_query_parameters", {}) or {}

        if filters is not None and len(filters) > 0:
            filters_str, extra_query_parameters = compose_filters_clause(
                filters, team_id=team_id, values=extra_query_parameters
            )
        else:
            filters_str, extra_query_parameters = "", extra_query_parameters

        full_range = (start, end)

        if batch_export.model["name"] == "persons":
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
            if batch_export.interval == "every 5 minutes" and not is_backfill:
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

            match batch_export.destination.type:
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

        return pa.Table.from_batches(self.clickhouse_client.stream_query_as_arrow(query, query_parameters=parameters))
