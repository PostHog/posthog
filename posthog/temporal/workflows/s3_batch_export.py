import datetime as dt
import json
from dataclasses import dataclass
from string import Template

from aiohttp import ClientSession
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from posthog.batch_exports.service import S3BatchExportInputs

from posthog.temporal.workflows.base import (
    CreateBatchExportRunInputs,
    PostHogWorkflow,
    UpdateBatchExportRunStatusInputs,
    create_export_run,
    update_export_run_status,
)

INSERT_INTO_S3_QUERY_TEMPLATE = Template(
    """
    INSERT INTO FUNCTION s3({path}, $auth {file_format})
    $partition_clause
    """
)

SELECT_QUERY_TEMPLATE = Template(
    """
    SELECT $fields
    FROM $table_name
    WHERE
        timestamp >= toDateTime({data_interval_start}, 'UTC')
        AND timestamp < toDateTime({data_interval_end}, 'UTC')
        AND team_id = {team_id}
    """
)

TABLE_PARTITION_KEYS = {
    "events": {
        "hour": "toStartOfHour(timestamp)",
        "day": "toStartOfDay(timestamp)",
        "week": "toStartOfWeek(timestamp)",
        "month": "toStartOfMonth(timestamp)",
    }
}


@dataclass
class S3InsertInputs:
    """Inputs for ClickHouse INSERT INTO S3 function."""

    bucket_name: str
    region: str
    key_template: str
    team_id: int
    data_interval_start: str
    data_interval_end: str
    file_format: str = "CSV"
    table_name: str = "events"
    partition_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None


def build_s3_url(bucket: str, region: str, key_template: str, is_debug_or_test: bool, **template_vars):
    """Form a S3 URL given input parameters.

    ClickHouse requires an S3 URL with http scheme.
    """
    if not template_vars:
        key = key_template
    else:
        key = key_template.format(**template_vars)

    if is_debug_or_test:
        # Note we are making a request to the object storage from the local ClickHouse container.
        # So, we are communicating via the network created by docker/podman compose. This means we
        # can use the service name to resolve to the object storage container.
        base_endpoint = "http://object-storage:19000"
    else:
        base_endpoint = f"https://s3.{region}.amazonaws.com"

    return f"{base_endpoint}/{bucket}/{key}"


def prepare_template_vars(inputs: S3InsertInputs):
    end_at = dt.datetime.fromisoformat(inputs.data_interval_end)
    return {
        "partition_id": "{_partition_id}",
        "table_name": inputs.table_name,
        "file_format": inputs.file_format,
        "datetime": inputs.data_interval_end,
        "year": end_at.year,
        "month": end_at.month,
        "day": end_at.day,
        "hour": end_at.hour,
        "minute": end_at.minute,
        "second": end_at.second,
    }


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """Activity that runs a INSERT INTO query in ClickHouse targetting an S3 table function."""
    from aiochclient import ChClient
    from django.conf import settings

    activity.logger.info("Running S3 export batch %s - %s", inputs.data_interval_start, inputs.data_interval_end)

    if inputs.table_name not in TABLE_PARTITION_KEYS:
        raise ValueError(f"Unsupported table {inputs.table_name}")

    if inputs.partition_key:
        if inputs.partition_key not in TABLE_PARTITION_KEYS[inputs.table_name]:
            raise ValueError(f"Unsupported partition_key {inputs.partition_key}")
        partition_clause = f"PARTITION BY {inputs.partition_key}"
    else:
        partition_clause = ""

    if inputs.aws_access_key_id is not None and inputs.aws_secret_access_key is not None:
        auth = "{aws_access_key_id}, {aws_secret_access_key},"
    else:
        auth = ""

    async with ClientSession() as s:
        client = ChClient(
            s,
            url=settings.CLICKHOUSE_HTTP_URL,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE,
        )

        if not await client.is_alive():
            raise ConnectionError("Cannot establish connection to ClickHouse")

        data_interval_start_ch = dt.datetime.fromisoformat(inputs.data_interval_start).strftime("%Y-%m-%d %H:%M:%S")
        data_interval_end_ch = dt.datetime.fromisoformat(inputs.data_interval_end).strftime("%Y-%m-%d %H:%M:%S")
        row = await client.fetchrow(
            SELECT_QUERY_TEMPLATE.substitute(table_name=inputs.table_name, fields="count(*)"),
            params={
                "team_id": inputs.team_id,
                "data_interval_start": data_interval_start_ch,
                "data_interval_end": data_interval_end_ch,
            },
        )
        count = row[0]

        if count is None or count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.", inputs.data_interval_start, inputs.data_interval_end
            )
            return

        activity.logger.info("BatchExporting %s rows to S3", count)

        template_vars = prepare_template_vars(inputs)
        s3_url = build_s3_url(
            bucket=inputs.bucket_name,
            region=inputs.region,
            key_template=inputs.key_template,
            is_debug_or_test=settings.TEST or settings.DEBUG,
            **template_vars,
        )

        query_template = Template(INSERT_INTO_S3_QUERY_TEMPLATE.template + SELECT_QUERY_TEMPLATE.template)

        activity.logger.debug(query_template.template)

        await client.execute(
            query_template.safe_substitute(
                table_name=inputs.table_name, fields="*", auth=auth, partition_clause=partition_clause
            ),
            params={
                "aws_access_key_id": inputs.aws_access_key_id,
                "aws_secret_access_key": inputs.aws_secret_access_key,
                "path": s3_url,
                "file_format": inputs.file_format,
                "team_id": inputs.team_id,
                "data_interval_start": data_interval_start_ch,
                "data_interval_end": data_interval_end_ch,
            },
        )


@workflow.defn(name="s3-export")
class S3BatchExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into S3.

    This Workflow is intended to be executed both manually and by a Temporal Schedule.
    When ran by a schedule, `data_interval_end` should be set to `None` so that we will fetch the
    end of the interval from the Temporal search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> S3BatchExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return S3BatchExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: S3BatchExportInputs):
        """Workflow implementation to export data to S3 bucket."""
        workflow.logger.info("Starting S3 export")

        data_interval_start, data_interval_end = get_data_interval_from_workflow_inputs(inputs)

        create_export_run_inputs = CreateBatchExportRunInputs(
            team_id=inputs.team_id,
            batch_export_id=inputs.batch_export_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(
            create_export_run,
            create_export_run_inputs,
            start_to_close_timeout=dt.timedelta(minutes=20),
            schedule_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                non_retryable_error_types=["NotNullViolation", "IntegrityError"],
            ),
        )

        update_inputs = UpdateBatchExportRunStatusInputs(id=run_id, status="Completed")

        insert_inputs = S3InsertInputs(
            bucket_name=inputs.bucket_name,
            region=inputs.region,
            key_template=inputs.key_template,
            partition_key=inputs.partition_key,
            table_name=inputs.table_name,
            team_id=inputs.team_id,
            file_format=inputs.file_format,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        try:
            await workflow.execute_activity(
                insert_into_s3_activity,
                insert_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    non_retryable_error_types=[
                        # If we can't connect to ClickHouse, no point in retrying.
                        "ConnectionError",
                        # Validation failed, and will keep failing.
                        "ValueError",
                    ],
                ),
            )

        except Exception as e:
            workflow.logger.exception("S3 BatchExport failed.", exc_info=e)
            update_inputs.status = "Failed"
            raise

        finally:
            await workflow.execute_activity(
                update_export_run_status,
                update_inputs,
                start_to_close_timeout=dt.timedelta(minutes=20),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )


def get_data_interval_from_workflow_inputs(inputs: S3BatchExportInputs) -> tuple[dt.datetime, dt.datetime]:
    """Return the start and end of an export's data interval.

    Args:
        inputs: The S3 BatchExport inputs.

    Raises:
        TypeError: If when trying to obtain the data interval end we run into non-str types.

    Returns:
        A tuple of two dt.datetime indicating start and end of the data_interval.
    """
    data_interval_end_str = inputs.data_interval_end

    if not data_interval_end_str:
        data_interval_end_search_attr = workflow.info().search_attributes.get("TemporalScheduledStartTime")

        # These two if-checks are a bit pedantic, but Temporal SDK is heavily typed.
        # So, they exist to make mypy happy.
        if data_interval_end_search_attr is None:
            msg = (
                "Expected 'TemporalScheduledStartTime' of type 'list[str]' or 'list[datetime], found 'NoneType'."
                "This should be set by the Temporal Schedule unless triggering workflow manually."
                "In the latter case, ensure 'S3BatchExportInputs.data_interval_end' is set."
            )
            raise TypeError(msg)

        # Failing here would perhaps be a bug in Temporal.
        if isinstance(data_interval_end_search_attr[0], str):
            data_interval_end_str = data_interval_end_search_attr[0]
            data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

        elif isinstance(data_interval_end_search_attr[0], dt.datetime):
            data_interval_end = data_interval_end_search_attr[0]

        else:
            msg = (
                f"Expected search attribute to be of type 'str' or 'datetime' found '{data_interval_end_search_attr[0]}' "
                f"of type '{type(data_interval_end_search_attr[0])}'."
            )
            raise TypeError(msg)
    else:
        data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

    data_interval_start = data_interval_end - dt.timedelta(seconds=inputs.batch_window_size)

    return (data_interval_start, data_interval_end)
