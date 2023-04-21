import datetime as dt
import json
from dataclasses import dataclass
from string import Template

from aiochclient import ChClient
from aiohttp import ClientSession
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.workflows.base import (
    CreateExportRunInputs,
    PostHogWorkflow,
    UpdateExportRunStatusInputs,
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
        timestamp >= {data_interval_start}
        AND timestamp < {data_interval_end}
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


def build_s3_url(bucket: str, region: str, key_template: str, **template_vars):
    """Form a S3 URL given input parameters.

    ClickHouse requires an S3 URL with http scheme.
    """
    if not template_vars:
        key = key_template
    else:
        key = key_template.format(**template_vars)

    return f"https://s3.{region}.amazonaws.com/{bucket}/{key}"


def prepare_template_vars(inputs: S3InsertInputs):
    return {
        "partition_id": "{_partition_id}",
        "table_name": inputs.table_name,
        "file_format": inputs.file_format,
    }


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """Activity that runs a INSERT INTO query in ClickHouse targetting an S3 table function."""
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
        client = ChClient(s)

        count = await client.fetchrow(
            SELECT_QUERY_TEMPLATE.substitute(table_name=inputs.table_name, fields="count(*)"),
            params={
                "team_id": inputs.team_id,
                "data_interval_start": dt.datetime.fromisoformat(inputs.data_interval_start),
                "data_interval_end": dt.datetime.fromisoformat(inputs.data_interval_end),
            },
        )
        count = count[0]

        if count is None or count == 0:
            activity.logger.info(
                "Nothing to export in batch %s - %s. Exiting.", inputs.data_interval_start, inputs.data_interval_end
            )
            return

        activity.logger.info("Exporting %s rows to S3", count)

        template_vars = prepare_template_vars(inputs)
        s3_url = build_s3_url(inputs.bucket_name, inputs.region, inputs.key_template, **template_vars)

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
                "data_interval_start": dt.datetime.fromisoformat(inputs.data_interval_start),
                "data_interval_end": dt.datetime.fromisoformat(inputs.data_interval_end),
            },
        )


@dataclass
class S3ExportInputs:
    """Inputs for S3 export workflow.

    Attributes:
        bucket_name: The S3 bucket we are exporting to.
        region: The AWS region where the bucket is located.
        file_name_prefix: A prefix for the file name to be created in S3.
        batch_window_size: The size in seconds of the batch window.
            For example, for one hour batches, this should be 3600.
        team_id: The team_id whose data we are exporting.
        file_format: The format of the file to be created in S3, supported by ClickHouse.
            A list of all supported formats can be found in https://clickhouse.com/docs/en/interfaces/formats.
        data_interval_end: For manual runs, the end date of the batch. This should be set to `None` for regularly
            scheduled runs and for backfills.
    """

    bucket_name: str
    region: str
    key_template: str
    batch_window_size: int
    team_id: int
    table_name: str = "events"
    file_format: str = "CSV"
    partition_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    data_interval_end: str | None = None


@workflow.defn(name="s3-export")
class S3ExportWorkflow(PostHogWorkflow):
    """A Temporal Workflow to export ClickHouse data into S3.

    This Workflow is intended to be executed both manually and by a Temporal Schedule.
    When ran by a schedule, `data_interval_end` should be set to `None` so that we will fetch the
    end of the interval from the Temporal search attribute `TemporalScheduledStartTime`.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> S3ExportInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return S3ExportInputs(**loaded)

    @workflow.run
    async def run(self, inputs: S3ExportInputs):
        """Workflow implementation to export data to S3 bucket."""
        workflow.logger.info("Starting S3 export")

        data_interval_end_str = inputs.data_interval_end or workflow.info.search_attributes.get(
            "TemporalScheduledStartTime"
        )
        data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

        data_interval_start = data_interval_end - dt.timedelta(seconds=inputs.batch_window_size)

        create_export_run_inputs = CreateExportRunInputs(
            team_id=inputs.team_id,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )
        run_id = await workflow.execute_activity(create_export_run, create_export_run_inputs)

        update_inputs = UpdateExportRunStatusInputs(run_id=run_id, status="Completed")

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
                start_to_close_timeout=dt.timedelta(seconds=60),
                schedule_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as e:
            workflow.logger.exception("S3 Export failed.", exc_info=e)
            update_inputs.status = "Failed"
        finally:
            await workflow.execute_activity(update_export_run_status, update_inputs)
