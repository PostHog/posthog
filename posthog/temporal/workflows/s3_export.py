import datetime as dt
import json
from dataclasses import dataclass

from aiochclient import ChClient
from aiohttp import ClientSession
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.workflows.base import CommandableWorkflow

INSERT_INTO_S3_TABLE = "INSERT INTO FUNCTION s3({path}, {file_format})"

INSERT_INTO_S3_TABLE_WITH_AUTH = """
INSERT INTO FUNCTION s3(
    {path},
    {aws_access_key_id},
    {aws_secret_access_key},
    {file_format}
)"""

SELECT_QUERY = """
SELECT *
FROM events
WHERE
    timestamp >= {data_interval_start}
    AND timestamp < {data_interval_end}
    AND team_id = {team_id}
"""

SELECT_COUNT_QUERY = """
SELECT count(*)
FROM events
WHERE
    timestamp >= {data_interval_start}
    AND timestamp < {data_interval_end}
    AND team_id = {team_id}
"""


@dataclass
class S3InsertInputs:
    """Inputs for ClickHouse INSERT INTO S3 function."""

    team_id: int
    s3_url: str
    file_format: str
    data_interval_start: str
    data_interval_end: str
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None


@activity.defn
async def insert_into_s3_activity(inputs: S3InsertInputs):
    """Activity that runs a INSERT INTO query in ClickHouse targetting an S3 table function."""
    activity.logger.info(f"Running S3 export batch {inputs.data_interval_start} - {inputs.data_interval_end}")

    if inputs.aws_access_key_id is not None and inputs.aws_secret_access_key is not None:
        query = INSERT_INTO_S3_TABLE_WITH_AUTH + SELECT_QUERY
    else:
        query = INSERT_INTO_S3_TABLE + SELECT_QUERY

    activity.logger.debug(query)

    async with ClientSession() as s:
        client = ChClient(s)

        count = await client.fetchrow(
            SELECT_COUNT_QUERY,
            params={
                "team_id": inputs.team_id,
                "data_interval_start": inputs.data_interval_start,
                "data_interval_end": inputs.data_interval_end,
            },
        )
        count = count[0]

        activity.logger.info(f"Exporting {count} rows to S3")

        await client.execute(
            query,
            params={
                "aws_access_key_id": inputs.aws_access_key_id,
                "aws_secret_access_key": inputs.aws_secret_access_key,
                "path": inputs.s3_url,
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
        s3_url: The S3 URL for the bucket we are exporting to.
        batch_window_size: The size in seconds of the batch window.
            For example, for one hour batches, this should be 3600.
        team_id: The team_id whose data we are exporting.
        file_format: The format of the file to be created in S3, supported by ClickHouse.
            A list of all supported formats can be found in https://clickhouse.com/docs/en/interfaces/formats.
        data_interval_end: For manual runs, the end date of the batch. This should be set to `None` for regularly
            scheduled runs and for backfills.
    """

    s3_url: str
    batch_window_size: int
    team_id: int
    file_format: str = "CSV"
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
            team_id=inputs.team_id,
            s3_url=inputs.s3_url,
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
