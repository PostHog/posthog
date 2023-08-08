from random import randint
from typing import Literal
from unittest import mock
from uuid import uuid4

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings

from ee.clickhouse.materialized_columns.columns import materialize
from posthog.temporal.tests.batch_exports.test_s3_batch_export_workflow import (
    insert_events,
    EventValues,
    create_test_client,
    assert_events_in_s3,
)
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.s3_batch_export import (
    S3InsertInputs,
    insert_into_s3_activity,
)


@sync_to_async
def amaterialize(table: Literal["events", "person", "groups"], column: str):
    """Materialize a column in a table."""
    return materialize(table, column)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_s3_activity_puts_data_into_s3(bucket_name, s3_client, activity_environment):
    """
    Test that the insert_into_s3_activity function puts data into S3. We do not
    assume anything about the Django models, and instead just check that the
    data is in S3.
    """

    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    # Add a materialized column such that we can verify that it is NOT included
    # in the export.
    await amaterialize("events", "$browser")

    # Create enough events to ensure we span more than 5MB, the smallest
    # multipart chunk size for multipart uploads to S3.
    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]

    events += [
        # Insert an events with an empty string in `properties` and
        # `person_properties` to ensure that we handle empty strings correctly.
        EventValues(
            {
                "uuid": str(uuid4()),
                "event": "test",
                "_timestamp": "2023-04-20 14:29:00",
                "timestamp": "2023-04-20 14:29:00.000000",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:29:00.000000",
                "distinct_id": str(uuid4()),
                "person_id": str(uuid4()),
                "person_properties": None,
                "team_id": team_id,
                "properties": None,
                "elements_chain": "",
            }
        )
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=client,
        events=events,
    )

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    other_team_id = team_id + 1
    await insert_events(
        client=client,
        events=[
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 13:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 15:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "inserted_at": "2023-04-20 13:30:00.000000",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 14:30:00",
                "_timestamp": "2023-04-20 14:30:00",
                "inserted_at": "2023-04-20 14:30:00.000000",
                "created_at": "2023-04-20 14:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": other_team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
        ],
    )

    # Make a random string to prefix the S3 keys with. This allows us to ensure
    # isolation of the test, and also to check that the data is being written.
    prefix = str(uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        with mock.patch("posthog.temporal.workflows.s3_batch_export.boto3.client", side_effect=create_test_client):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert_events_in_s3(s3_client, bucket_name, prefix, events)
