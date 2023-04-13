import datetime as dt
import json
from dataclasses import dataclass
from string import Template

from aiochclient import ChClient
from aiohttp import ClientSession
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.workflows.base import CommandableWorkflow

INSERT_INTO_S3_QUERY_TEMPLATE = Template(
    """
    INSERT INTO FUNCTION s3({path}, $authentication {file_format})
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
    file_name_prefix: str
    team_id: int
    data_interval_start: str
    data_interval_end: str
    file_format: str = "CSV"
    table_name: str = "events"
    partition_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None


def build_s3_url(bucket: str, region: str, file_name_prefix: str, partition_key: str):
    """Form a S3 URL given input parameters.

    ClickHouse requires an S3 URL with http scheme.
    """
    if partition_key:
        file_name_prefix += "_{_partition_id}"
    return f"https://s3.{region}.amazonaws.com/{bucket}/{file_name_prefix}"


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """Activity that runs a INSERT INTO query in ClickHouse targetting an S3 table function."""
    activity.logger.info(f"Running S3 export batch {inputs.data_interval_start} - {inputs.data_interval_end}")

    if inputs.table_name not in TABLE_PARTITION_KEYS:
        raise ValueError(f"Unsupported table {inputs.table_name}")

    if inputs.partition_key not in TABLE_PARTITION_KEYS[inputs.table_name]:
        raise ValueError(f"Unsupported partition_key {inputs.partition_key}")

    if inputs.partition_key:
        partition_clause = f"PARTITION BY {inputs.partition_key}"
    else:
        partition_clause = ""

    if inputs.aws_access_key_id is not None and inputs.aws_secret_access_key is not None:
        auth = "{aws_access_key_id}, {aws_secret_access_key},"
    else:
        auth = ""

    query_template = Template(INSERT_INTO_S3_QUERY_TEMPLATE.template + SELECT_QUERY_TEMPLATE.template)

    activity.logger.debug(query_template.template)

    async with ClientSession() as s:
        client = ChClient(s)

        count = await client.fetchrow(
            SELECT_QUERY_TEMPLATE.substitute(table_name=inputs.table_name, fields="count(*)"),
            params={
                "team_id": inputs.team_id,
                "data_interval_start": inputs.data_interval_start,
                "data_interval_end": inputs.data_interval_end,
            },
        )
        count = count[0]

        if count is None or count == 0:
            activity.logger.info(
                f"Nothing to export in batch {inputs.data_interval_start} - {inputs.data_interval_end}. Exiting."
            )
            return

        activity.logger.info(f"Exporting {count} rows to S3")

        s3_url = build_s3_url(inputs.bucket_name, inputs.region, inputs.file_name_prefix, inputs.partition_key)

        await client.execute(
            query_template.substitute(
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
    file_name_prefix: str
    batch_window_size: int
    team_id: int
    table_name: str = "events"
    file_format: str = "CSV"
    partition_key: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    data_interval_end: str | None = None


@workflow.defn(name="s3-export")
class S3ExportWorkflow(CommandableWorkflow):
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
        workflow.logger.info(f"Starting S3 export")

        data_interval_end_str = inputs.data_interval_end or workflow.info.search_attributes.get(
            "TemporalScheduledStartTime"
        )
        data_interval_end = dt.datetime.fromisoformat(data_interval_end_str)

        data_interval_start = data_interval_end - dt.timedelta(seconds=inputs.batch_window_size)

        insert_inputs = S3InsertInputs(
            bucket_name=inputs.bucket_name,
            region=inputs.region,
            file_name_prefix=inputs.file_name_prefix,
            partition_key=inputs.partition_key,
            table_name=inputs.table_name,
            team_id=inputs.team_id,
            file_format=inputs.file_format,
            aws_access_key_id=inputs.aws_access_key_id,
            aws_secret_access_key=inputs.aws_secret_access_key,
            data_interval_start=data_interval_start.isoformat(),
            data_interval_end=data_interval_end.isoformat(),
        )

        await workflow.execute_activity(
            insert_into_s3_activity,
            insert_inputs,
            start_to_close_timeout=dt.timedelta(seconds=60),
            schedule_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
