import asyncio
import datetime as dt
import functools
import unittest.mock
import uuid

import aioboto3
import dlt
import pytest
import pytest_asyncio
import temporalio.common
import temporalio.testing
import temporalio.worker
from django.conf import settings
from django.test import override_settings
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
from dlt.common.libs.deltalake import get_delta_tables

from posthog import constants
from posthog.hogql.database.database import create_hogql_database
from posthog.models import Team
from posthog.temporal.data_modeling.run_workflow import (
    BuildDagActivityInputs,
    ModelNode,
    RunDagActivityInputs,
    RunWorkflow,
    RunWorkflowInputs,
    build_dag_activity,
    finish_run_activity,
    get_dlt_destination,
    materialize_model,
    run_dag_activity,
    start_run_activity,
)
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.modeling import DataWarehouseModelPath
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
            "events": ModelNode(label="events", children={"my_events_model"}),
            "persons": ModelNode(label="persons", children={"my_persons_model"}),
            "my_events_model": ModelNode(
                label="my_events_model", children={"my_joined_model"}, parents={"events"}, selected=True
            ),
            "my_persons_model": ModelNode(
                label="my_persons_model", children={"my_joined_model"}, parents={"persons"}, selected=True
            ),
            "my_joined_model": ModelNode(
                label="my_joined_model", parents={"my_events_model", "my_persons_model"}, selected=True
            ),
        },
    ],
)
async def test_run_dag_activity_activity_materialize_mocked(activity_environment, ateam, dag, posthog_tables):
    """Test all models are completed with a mocked materialize."""
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
                "events": ModelNode(label="events", children={"my_events_model"}),
                "persons": ModelNode(label="persons", children={"my_persons_model"}),
                "my_events_model": ModelNode(
                    label="my_events_model", children={"my_joined_model"}, parents={"events"}, selected=True
                ),
                "my_persons_model": ModelNode(
                    label="my_persons_model", children={"my_joined_model"}, parents={"persons"}, selected=True
                ),
                "my_joined_model": ModelNode(
                    label="my_joined_model",
                    children={"my_read_from_joined_model"},
                    parents={"my_events_model", "my_persons_model"},
                    selected=True,
                ),
                "my_read_from_joined_model": ModelNode(
                    label="my_read_from_joined_model", parents={"my_joined_model"}, selected=True
                ),
            },
            ("my_events_model",),
        ),
    ],
)
async def test_run_dag_activity_activity_skips_if_ancestor_failed_mocked(
    activity_environment, ateam, dag, make_fail, posthog_tables
):
    """Test some models are completed while some fail with a mocked materialize.

    Args:
        dag: The dictionary of `ModelNode`s representing the model DAG.
        make_fail: A sequence of model labels of models that should fail to check they are
            handled properly.
    """
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
        clickhouse_client,
        ateam.pk,
        start_time,
        end_time,
        event_name="$pageview",
        count=50,
        count_outside_range=0,
        distinct_ids=["a", "b"],
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


@pytest_asyncio.fixture
async def saved_queries(ateam):
    parent_query = """\
      select
        events.event as event,
        events.distinct_id as distinct_id,
        events.timestamp as timestamp
      from events
      where events.event = '$pageview'
    """
    parent_saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="my_model",
        query={"query": parent_query, "kind": "HogQLQuery"},
    )
    child_saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="my_model_child",
        query={"query": "select * from my_model where distinct_id = 'b'", "kind": "HogQLQuery"},
    )
    child_2_saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="my_model_child_2",
        query={"query": "select * from my_model where distinct_id = 'a'", "kind": "HogQLQuery"},
    )
    grand_child_saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam,
        name="my_model_grand_child",
        query={"query": "select * from my_model_child union all select * from my_model_child_2", "kind": "HogQLQuery"},
    )
    await database_sync_to_async(DataWarehouseModelPath.objects.create_from_saved_query)(parent_saved_query)
    await database_sync_to_async(DataWarehouseModelPath.objects.create_from_saved_query)(child_saved_query)
    await database_sync_to_async(DataWarehouseModelPath.objects.create_from_saved_query)(child_2_saved_query)
    await database_sync_to_async(DataWarehouseModelPath.objects.create_from_saved_query)(grand_child_saved_query)

    yield parent_saved_query, child_saved_query, child_2_saved_query, grand_child_saved_query


async def test_build_dag_activity_select_all_ancestors(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select all ancestors of a model using a single '+' prefix.
    """
    parent_saved_query, child_saved_query, _, grand_child_saved_query = saved_queries

    select = [f"+{child_saved_query.id.hex}"]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex}
    assert dag[parent_saved_query.id.hex].selected is True

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].selected is True

    selected = (
        child_saved_query.id.hex,
        parent_saved_query.id.hex,
    )
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_all_descendants(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select all descendants of a model using a single '+' suffix.
    """
    parent_saved_query, child_saved_query, child_2_saved_query, grand_child_saved_query = saved_queries

    select = [f"{parent_saved_query.id.hex}+"]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex, child_2_saved_query.id.hex}
    assert dag[parent_saved_query.id.hex].selected is True

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].selected is True

    assert dag[child_2_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].selected is True

    assert dag[grand_child_saved_query.id.hex].parents == {child_saved_query.id.hex, child_2_saved_query.id.hex}
    assert not dag[grand_child_saved_query.id.hex].children
    assert dag[grand_child_saved_query.id.hex].selected is True

    selected = (
        grand_child_saved_query.id.hex,
        child_2_saved_query.id.hex,
        child_saved_query.id.hex,
        parent_saved_query.id.hex,
    )
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_multiple_individual_models(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we select multiple individual models to assert that:
    * All selected models are marked as selected to run.
    * Additional models are included to account for paths connecting models.
    * These additional models are not marked as selected.
    """
    parent_saved_query, child_saved_query, child_2_saved_query, _ = saved_queries

    select = [parent_saved_query.id.hex, child_saved_query.id.hex, child_2_saved_query.id.hex]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert len(dag) == 5
    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex, child_2_saved_query.id.hex}

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].parents == {parent_saved_query.id.hex}

    assert all(dag[selected].selected is True for selected in select)
    assert all(dag[other].selected is False for other in dag.keys() if other not in select)


async def test_build_dag_activity_select_first_parents(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select first parents of a model using a '1+' prefix.
    """
    _, child_saved_query, child_2_saved_query, grand_child_saved_query = saved_queries

    select = [f"1+{grand_child_saved_query.id.hex}"]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[child_2_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[grand_child_saved_query.id.hex].parents == {child_2_saved_query.id.hex, child_saved_query.id.hex}

    selected = (
        child_saved_query.id.hex,
        child_2_saved_query.id.hex,
        grand_child_saved_query.id.hex,
    )
    assert all(dag[selected].selected is True for selected in selected)
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_first_children(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select first children of a model using a '+1' suffix.
    """
    parent_saved_query, child_saved_query, child_2_saved_query, _ = saved_queries

    select = [f"{parent_saved_query.id.hex}+1"]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[child_2_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[parent_saved_query.id.hex].children == {child_2_saved_query.id.hex, child_saved_query.id.hex}

    selected = (
        child_saved_query.id.hex,
        child_2_saved_query.id.hex,
        parent_saved_query.id.hex,
    )
    assert all(dag[selected].selected is True for selected in selected)
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_first_family(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select first children and first parents of a model using a
    both a'+1' suffix and a '1+' prefix.
    """
    parent_saved_query, child_saved_query, _, grand_child_saved_query = saved_queries

    select = [f"1+{child_saved_query.id.hex}+1"]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[grand_child_saved_query.id.hex].parents == {child_saved_query.id.hex}
    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex}

    selected = (
        child_saved_query.id.hex,
        parent_saved_query.id.hex,
        grand_child_saved_query.id.hex,
    )
    assert all(dag[selected].selected is True for selected in selected)
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_all(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select all models by not passing any selectors.
    """
    parent_saved_query, child_saved_query, child_2_saved_query, grand_child_saved_query = saved_queries

    inputs = BuildDagActivityInputs(team_id=ateam.pk)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].children == {grand_child_saved_query.id.hex}
    assert dag[grand_child_saved_query.id.hex].parents == {child_saved_query.id.hex, child_2_saved_query.id.hex}
    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex, child_2_saved_query.id.hex}

    assert all(dag[selected].selected is True for selected in dag.keys() if selected not in {"events", "persons"})


async def test_run_workflow_with_minio_bucket(
    minio_client,
    ateam,
    bucket_name,
    pageview_events,
    saved_queries,
    temporal_client,
):
    """Test run workflow end-to-end using a local MinIO bucket."""
    events, _ = pageview_events
    all_expected_events = sorted(
        [
            {
                k: dt.datetime.fromisoformat(v).replace(tzinfo=dt.UTC) if k == "timestamp" else v
                for k, v in event.items()
                if k in ("event", "distinct_id", "timestamp")
            }
            for event in events
        ],
        key=lambda d: (d["distinct_id"], d["timestamp"]),
    )
    expected_events_a = [event for event in all_expected_events if event["distinct_id"] == "a"]
    expected_events_b = [event for event in all_expected_events if event["distinct_id"] == "b"]

    workflow_id = str(uuid.uuid4())
    inputs = RunWorkflowInputs(team_id=ateam.pk)

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
        async with temporalio.worker.Worker(
            temporal_client,
            task_queue=constants.DATA_WAREHOUSE_TASK_QUEUE,
            workflows=[RunWorkflow],
            activities=[
                start_run_activity,
                build_dag_activity,
                run_dag_activity,
                finish_run_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await temporal_client.execute_workflow(
                RunWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.DATA_WAREHOUSE_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )
        destination = get_dlt_destination()
        tables_and_queries = {}

        for query in saved_queries:
            await database_sync_to_async(query.refresh_from_db)()

            pipeline = dlt.pipeline(
                pipeline_name=f"materialize_model_{query.id.hex}",
                destination=destination,
                dataset_name=f"team_{ateam.pk}_model_{query.id.hex}",
            )

            tables = get_delta_tables(pipeline)
            key, delta_table = tables.popitem()
            # All test tables have the same columns, which is a limitation of our test
            table = delta_table.to_pyarrow_table(columns=["event", "distinct_id", "timestamp"])
            tables_and_queries[key] = (table, query)

        for key, table_and_query in tables_and_queries.items():
            table, query = table_and_query

            if "distinct_id = 'a'" in query.query["query"]:
                expected_data = expected_events_a
            elif "distinct_id = 'b'" in query.query["query"]:
                expected_data = expected_events_b
            else:
                expected_data = all_expected_events

            assert table.num_rows == len(expected_data)
            assert table.num_columns == 3
            assert table.column_names == ["event", "distinct_id", "timestamp"]
            assert key == query.name
            assert sorted(table.to_pylist(), key=lambda d: (d["distinct_id"], d["timestamp"])) == expected_data
            assert query.last_run_status == DataWarehouseSavedQuery.Status.COMPLETED
