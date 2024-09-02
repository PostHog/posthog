import asyncio
import datetime as dt
import functools
import unittest.mock
import uuid

import aioboto3
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from dlt.common.configuration.specs.aws_credentials import AwsCredentials

from posthog.hogql.database.database import create_hogql_database
from posthog.models import Team
from posthog.temporal.data_modeling.run_workflow import (
    ModelNode,
    RunDagActivityInputs,
    materialize_model,
    run_dag_activity,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.util import database_sync_to_async

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]


@pytest_asyncio.fixture
async def posthog_tables(ateam):
    team = await database_sync_to_async(Team.objects.get)(id=ateam.pk)
    hogql_db = await database_sync_to_async(create_hogql_database)(team_id=ateam.pk, team_arg=team)
    posthog_tables = hogql_db.get_posthog_tables()

    return posthog_tables


@pytest.mark.parametrize(
    "dag",
    [
        {
            "events": ModelNode(label="events", children={"my_events_model"}, parents=set()),
            "persons": ModelNode(label="persons", children={"my_persons_model"}, parents=set()),
            "my_events_model": ModelNode(label="my_events_model", children={"my_joined_model"}, parents={"events"}),
            "my_persons_model": ModelNode(label="my_persons_model", children={"my_joined_model"}, parents={"persons"}),
            "my_joined_model": ModelNode(
                label="my_joined_model", children=set(), parents={"my_events_model", "my_persons_model"}
            ),
        },
    ],
)
async def test_run_dag_activity_activity_materialize_mocked(activity_environment, ateam, dag, posthog_tables):
    run_dag_activity_inputs = RunDagActivityInputs(team_id=ateam.pk, dag=dag)

    magic_mock = unittest.mock.AsyncMock()
    with unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", new=magic_mock):
        async with asyncio.timeout(10):
            results = await activity_environment.run(run_dag_activity, run_dag_activity_inputs)

        models_materialized = [model for model in dag.keys() if model not in posthog_tables]

    calls = magic_mock.mock_calls

    assert all(
        call.args[0] in models_materialized for call in calls
    ), f"Found models that shouldn't have been materialized: {tuple(call.args[0] for call in calls if call.args[0] not in models_materialized)}"
    assert all(
        call.args[1].pk == ateam.pk for call in calls
    ), f"Found team ids that do not match test team ({ateam.pk}): {tuple(call.args[1].pk for call in calls)}"
    assert len(calls) == len(models_materialized)
    assert results.completed == set(dag.keys())


@pytest.mark.parametrize(
    "dag,make_fail",
    [
        (
            {
                "events": ModelNode(label="events", children={"my_events_model"}, parents=set()),
                "persons": ModelNode(label="persons", children={"my_persons_model"}, parents=set()),
                "my_events_model": ModelNode(label="my_events_model", children={"my_joined_model"}, parents={"events"}),
                "my_persons_model": ModelNode(
                    label="my_persons_model", children={"my_joined_model"}, parents={"persons"}
                ),
                "my_joined_model": ModelNode(
                    label="my_joined_model",
                    children={"my_read_from_joined_model"},
                    parents={"my_events_model", "my_persons_model"},
                ),
                "my_read_from_joined_model": ModelNode(
                    label="my_read_from_joined_model", children=set(), parents={"my_joined_model"}
                ),
            },
            ("my_events_model",),
        ),
    ],
)
async def test_run_dag_activity_activity_skips_if_ancestor_failed_mocked(
    activity_environment, ateam, dag, make_fail, posthog_tables
):
    run_dag_activity_inputs = RunDagActivityInputs(team_id=ateam.pk, dag=dag)
    assert all(model not in posthog_tables for model in make_fail), "PostHog tables cannot fail"

    def raise_if_should_make_fail(model_label, *args, **kwargs):
        if model_label in make_fail:
            raise ValueError("Oh no!")

    expected_failed = set()
    expected_ancestor_failed = set()

    for model in make_fail:
        expected_failed.add(model)

        children_to_fail = list(dag[model].children)
        while children_to_fail:
            child = children_to_fail.pop()
            expected_ancestor_failed.add(child)

            children_to_fail.extend(list(dag[child].children))

    expected_completed = {
        key for key in dag.keys() if key not in expected_failed and key not in expected_ancestor_failed
    }

    magic_mock = unittest.mock.AsyncMock(side_effect=raise_if_should_make_fail)
    with unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", new=magic_mock):
        async with asyncio.timeout(10):
            results = await activity_environment.run(run_dag_activity, run_dag_activity_inputs)

        models_materialized = [model for model in expected_failed | expected_completed if model not in posthog_tables]

    calls = magic_mock.mock_calls

    assert all(
        call.args[0] in models_materialized for call in calls
    ), f"Found models that shouldn't have been materialized: {tuple(call.args[0] for call in calls if call.args[0] not in models_materialized)}"
    assert all(
        call.args[1].pk == ateam.pk for call in calls
    ), f"Found team ids that do not match test team ({ateam.pk}): {tuple(call.args[1].pk for call in calls)}"
    assert len(calls) == len(models_materialized)

    assert results.completed == expected_completed
    assert results.failed == expected_failed
    assert results.ancestor_failed == expected_ancestor_failed


TEST_ROOT_BUCKET = "test-data-modeling"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as minio_client:
        try:
            await minio_client.head_bucket(Bucket=bucket_name)
        except:
            await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client


def mock_to_session_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "aws_session_token": None,
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


def mock_to_object_store_rs_credentials(class_self):
    return {
        "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
        "region": "us-east-1",
        "AWS_ALLOW_HTTP": "true",
        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
    }


@pytest_asyncio.fixture
async def pageview_events(clickhouse_client, ateam):
    start_time, end_time = dt.datetime.now(dt.UTC) - dt.timedelta(days=1), dt.datetime.now(dt.UTC)
    events, _, events_from_other_team = await generate_test_events_in_clickhouse(
        clickhouse_client, ateam.pk, start_time, end_time, event_name="$pageview", count=50, count_outside_range=0
    )
    return (events, events_from_other_team)


async def test_materialize_model(ateam, bucket_name, minio_client, pageview_events):
    query = """\
    select
      event as event,
      if(distinct_id != '0', distinct_id, null) as distinct_id,
      timestamp as timestamp
    from events
    where event = '$pageview'
    """
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="my_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        unittest.mock.patch.object(
            AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials
        ),
    ):
        key, delta_table = await materialize_model(saved_query.id.hex, ateam)

    s3_objects = await minio_client.list_objects_v2(
        Bucket=bucket_name, Prefix=f"team_{ateam.pk}_model_{saved_query.id.hex}/"
    )
    table = delta_table.to_pyarrow_table(columns=["event", "distinct_id", "timestamp"])
    events, _ = pageview_events
    expected_events = sorted(
        [
            {
                k: dt.datetime.fromisoformat(v).replace(tzinfo=dt.UTC) if k == "timestamp" else v
                for k, v in event.items()
                if k in ("event", "distinct_id", "timestamp")
            }
            for event in events
        ],
        key=lambda d: d["distinct_id"],
    )

    assert table.num_rows == len(expected_events)
    assert table.num_columns == 3
    assert table.column_names == ["event", "distinct_id", "timestamp"]
    assert len(s3_objects["Contents"]) != 0
    assert key == saved_query.name
    assert sorted(table.to_pylist(), key=lambda d: d["distinct_id"]) == expected_events
