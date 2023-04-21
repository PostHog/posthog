import datetime as dt
from unittest import mock

import pytest
from temporalio.testing import ActivityEnvironment

from posthog.temporal.workflows.s3_export import (
    S3InsertInputs,
    build_s3_url,
    insert_into_s3_activity,
)


@pytest.fixture
def activity_environment():
    """Return a testing temporal ActivityEnvironment."""
    return ActivityEnvironment()


@pytest.mark.parametrize(
    "inputs,expected",
    [
        (
            {
                "bucket": "my-test-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/events_{partition_id}.csv",
                "partition_id": "{_partition_id}",
            },
            "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.csv",
        ),
        (
            {
                "bucket": "my-test-bucket",
                "region": "us-east-1",
                "key_template": "posthog-{table_name}/{table_name}_{partition_id}.csv",
                "partition_id": "{_partition_id}",
                "table_name": "events",
            },
            "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.csv",
        ),
        (
            {
                "bucket": "my-test-bucket-2",
                "region": "eu-west-1",
                "key_template": "events.parquet",
            },
            "https://s3.eu-west-1.amazonaws.com/my-test-bucket-2/events.parquet",
        ),
    ],
)
def test_build_s3_url(inputs, expected):
    """Test the build_s3_url utility function used in the S3Export workflow."""
    result = build_s3_url(**inputs)
    assert result == expected


@pytest.mark.asyncio
async def test_insert_into_s3_activity(activity_environment):
    """Test the insert_into_s3_activity part of the S3Export workflow.

    We mock calls to the ClickHouse client and assert the queries sent to it.
    """
    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-20 15:00:00"
    team_id = 2
    file_format = "Parquet"

    insert_inputs = S3InsertInputs(
        bucket_name="my-test-bucket",
        region="us-east-1",
        key_template="posthog-{table_name}/{table_name}_{partition_id}.parquet",
        team_id=team_id,
        file_format=file_format,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )

    expected_s3_url = "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.parquet"

    expected_fetch_row_query = """
    SELECT count(*)
    FROM events
    WHERE
        timestamp >= {data_interval_start}
        AND timestamp < {data_interval_end}
        AND team_id = {team_id}
    """

    # Excuse the format. I have to make indentation match for the assert_awaited_once_with call to pass.
    expected_execute_row_query = """
    INSERT INTO FUNCTION s3({path},  {file_format})\n    \n    \n    SELECT *
    FROM events
    WHERE
        timestamp >= {data_interval_start}
        AND timestamp < {data_interval_end}
        AND team_id = {team_id}
    """

    with mock.patch("posthog.temporal.workflows.s3_export.ChClient.fetchrow") as fetch_row:
        with mock.patch("posthog.temporal.workflows.s3_export.ChClient.execute") as execute:
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

            fetch_row.assert_awaited_once_with(
                expected_fetch_row_query,
                params={
                    "team_id": team_id,
                    "data_interval_start": dt.datetime.fromisoformat(data_interval_start),
                    "data_interval_end": dt.datetime.fromisoformat(data_interval_end),
                },
            )
            execute.assert_awaited_once_with(
                expected_execute_row_query,
                params={
                    "aws_access_key_id": None,
                    "aws_secret_access_key": None,
                    "path": expected_s3_url,
                    "file_format": file_format,
                    "team_id": team_id,
                    "data_interval_start": dt.datetime.fromisoformat(data_interval_start),
                    "data_interval_end": dt.datetime.fromisoformat(data_interval_end),
                },
            )
