import os
import re
import uuid
import asyncio
import datetime as dt

import pytest
import unittest.mock
from freezegun.api import freeze_time

from django.conf import settings
from django.test import override_settings

import pyarrow as pa
import deltalake
import pytest_asyncio
import temporalio.common
import temporalio.worker
from asgiref.sync import sync_to_async
from temporalio import (
    activity as temporal_activity,
    workflow as temporal_workflow,
)
from temporalio.testing import WorkflowEnvironment

from posthog.hogql.database.database import Database
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team
from posthog.models.event.util import bulk_create_events
from posthog.sync import database_sync_to_async
from posthog.temporal.data_modeling import run_workflow as run_workflow_module
from posthog.temporal.data_modeling.run_workflow import (
    BuildDagActivityInputs,
    CleanupRunningJobsActivityInputs,
    CreateJobModelInputs,
    ModelNode,
    NonRetryableException,
    RunDagActivityInputs,
    RunWorkflow,
    RunWorkflowInputs,
    Selector,
    build_dag_activity,
    cleanup_running_jobs_activity,
    create_job_model_activity,
    fail_jobs_activity,
    finish_run_activity,
    materialize_model,
    run_dag_activity,
    start_run_activity,
)
from posthog.temporal.ducklake.types import DuckLakeCopyModelInput
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse, truncate_table

from products.data_warehouse.backend.models.data_modeling_job import DataModelingJob
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.modeling import DataWarehouseModelPath
from products.data_warehouse.backend.models.table import DataWarehouseTable

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_TIME = dt.datetime.now(dt.UTC)


@pytest_asyncio.fixture
async def posthog_table_names(ateam):
    team = await database_sync_to_async(Team.objects.get)(id=ateam.pk)
    hogql_db = await database_sync_to_async(Database.create_for)(team=team)
    posthog_table_names = hogql_db.get_posthog_table_names()

    return posthog_table_names


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
async def test_run_dag_activity_activity_materialize_mocked(activity_environment, ateam, dag, posthog_table_names):
    """Test all models are completed with a mocked materialize."""
    for model_label in dag.keys():
        if model_label not in posthog_table_names:
            await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
                team=ateam,
                name=model_label,
                query={"query": f"SELECT * FROM events LIMIT 10", "kind": "HogQLQuery"},
            )

    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
    )
    run_dag_activity_inputs = RunDagActivityInputs(team_id=ateam.pk, dag=dag, job_id=job.id)

    magic_mock = unittest.mock.AsyncMock(return_value=("test_key", unittest.mock.MagicMock(), uuid.uuid4()))

    with unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", new=magic_mock):
        async with asyncio.timeout(10):
            results = await activity_environment.run(run_dag_activity, run_dag_activity_inputs)

        models_materialized = [model for model in dag.keys() if model not in posthog_table_names]

    calls = magic_mock.mock_calls

    assert all(call.args[0] in models_materialized for call in calls), (
        f"Found models that shouldn't have been materialized: {tuple(call.args[0] for call in calls if call.args[0] not in models_materialized)}"
    )
    assert all(call.args[1].pk == ateam.pk for call in calls), (
        f"Found team ids that do not match test team ({ateam.pk}): {tuple(call.args[1].pk for call in calls)}"
    )
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
    activity_environment, ateam, dag, make_fail, posthog_table_names
):
    """Test some models are completed while some fail with a mocked materialize.

    Args:
        dag: The dictionary of `ModelNode`s representing the model DAG.
        make_fail: A sequence of model labels of models that should fail to check they are
            handled properly.
    """
    # Create the necessary saved queries for the test
    for model_label in dag.keys():
        if model_label not in posthog_table_names:
            await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
                team=ateam,
                name=model_label,
                query={"query": f"SELECT * FROM events LIMIT 10", "kind": "HogQLQuery"},
            )

    job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam,
    )
    run_dag_activity_inputs = RunDagActivityInputs(team_id=ateam.pk, dag=dag, job_id=job.id)
    assert all(model not in posthog_table_names for model in make_fail), "PostHog tables cannot fail"

    def raise_if_should_make_fail(model_label, *args, **kwargs):
        if model_label in make_fail:
            raise ValueError("Oh no!")
        return ("test_key", unittest.mock.MagicMock(), uuid.uuid4())

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

        models_materialized = [
            model for model in expected_failed | expected_completed if model not in posthog_table_names
        ]

    calls = magic_mock.mock_calls

    assert all(call.args[0] in models_materialized for call in calls), (
        f"Found models that shouldn't have been materialized: {tuple(call.args[0] for call in calls if call.args[0] not in models_materialized)}"
    )
    assert all(call.args[1].pk == ateam.pk for call in calls), (
        f"Found team ids that do not match test team ({ateam.pk}): {tuple(call.args[1].pk for call in calls)}"
    )
    assert len(calls) == len(models_materialized)

    assert results.completed == expected_completed
    assert results.failed == expected_failed
    assert results.ancestor_failed == expected_ancestor_failed


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
async def truncate_events_table(clickhouse_client):
    await truncate_table(clickhouse_client, "sharded_events")


@pytest_asyncio.fixture
async def pageview_events(clickhouse_client, ateam, truncate_events_table):
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
        table="sharded_events",
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

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

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
        key=lambda d: (d["distinct_id"], d["timestamp"]),
    )

    query_folder_pattern = re.compile(r"^.+?\_\_query\_\d+\/.+")

    assert any(query_folder_pattern.match(obj["Key"]) for obj in s3_objects["Contents"])
    assert any(f"{saved_query.normalized_name}__query" in obj["Key"] for obj in s3_objects["Contents"])
    assert table.num_rows == len(expected_events)
    assert table.num_columns == 3
    assert table.column_names == ["event", "distinct_id", "timestamp"]
    assert len(s3_objects["Contents"]) != 0
    assert key == saved_query.normalized_name
    assert sorted(table.to_pylist(), key=lambda d: (d["distinct_id"], d["timestamp"])) == expected_events

    # Ensure we can query the table
    await sync_to_async(execute_hogql_query)(f"SELECT * FROM {saved_query.name}", ateam)


async def test_materialize_model_timestamps(ateam, bucket_name, minio_client, pageview_events):
    query = """\
    select toDateTime64(toDateTime('2025-01-01T00:00:00.000'), 3, 'Asia/Istanbul') as now_converted, toDateTime('2025-01-01T00:00:00.000') as now
    """
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="my_model",
        query={"query": query, "kind": "HogQLQuery"},
    )
    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        _, delta_table, _ = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

    table = delta_table.to_pyarrow_table(columns=["now_converted", "now"])
    assert table.num_rows == 1
    assert table.num_columns == 2
    assert table.column_names == ["now_converted", "now"]
    assert table.column(0).type == pa.timestamp("us", tz="UTC")
    assert table.column(1).type == pa.timestamp("us", tz="UTC")

    # replace microsecond because they won't match exactly
    row = table.to_pylist()[0]
    now_converted = row["now_converted"]
    now = row["now"]
    assert now_converted == now


async def test_materialize_model_nullable_nothing_column(ateam, bucket_name, minio_client, pageview_events):
    query = """\
    select NULL as nullable_nothing_column, toTypeName(nullable_nothing_column) as nullable_nothing_column_type
    """
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="my_model",
        query={"query": query, "kind": "HogQLQuery"},
    )
    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        _, delta_table, _ = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

    table = delta_table.to_pyarrow_table(columns=["nullable_nothing_column", "nullable_nothing_column_type"])
    assert table.num_rows == 1
    assert table.num_columns == 2
    assert table.column_names == ["nullable_nothing_column", "nullable_nothing_column_type"]
    assert table.column(0).type == pa.string()  # Mapped to a string even though it was null


async def test_materialize_model_with_pascal_cased_name(ateam, bucket_name, minio_client, pageview_events):
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
        name="PascalCasedView",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

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
        key=lambda d: (d["distinct_id"], d["timestamp"]),
    )

    query_folder_pattern = re.compile(r"^.+?\_\_query\_\d+\/.+")

    assert any(query_folder_pattern.match(obj["Key"]) for obj in s3_objects["Contents"])
    assert any(f"{saved_query.normalized_name}__query" in obj["Key"] for obj in s3_objects["Contents"])
    assert table.num_rows == len(expected_events)
    assert table.num_columns == 3
    assert table.column_names == ["event", "distinct_id", "timestamp"]
    assert len(s3_objects["Contents"]) != 0
    assert key == saved_query.normalized_name
    assert sorted(table.to_pylist(), key=lambda d: (d["distinct_id"], d["timestamp"])) == expected_events

    # Ensure we can query the table
    await sync_to_async(execute_hogql_query)(f"SELECT * FROM {saved_query.name}", ateam)


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
    parent_saved_query = DataWarehouseSavedQuery(
        team=ateam,
        name="my_model",
        query={"query": parent_query, "kind": "HogQLQuery"},
    )
    parent_saved_query.columns = await sync_to_async(parent_saved_query.get_columns)()
    await parent_saved_query.asave()

    child_saved_query = DataWarehouseSavedQuery(
        team=ateam,
        name="my_model_child",
        query={"query": "select * from my_model where distinct_id = 'b'", "kind": "HogQLQuery"},
    )
    child_saved_query.columns = await sync_to_async(child_saved_query.get_columns)()
    await child_saved_query.asave()

    child_2_saved_query = DataWarehouseSavedQuery(
        team=ateam,
        name="my_model_child_2",
        query={"query": "select * from my_model where distinct_id = 'a'", "kind": "HogQLQuery"},
    )
    child_2_saved_query.columns = await sync_to_async(child_2_saved_query.get_columns)()
    await child_2_saved_query.asave()

    grand_child_saved_query = DataWarehouseSavedQuery(
        team=ateam,
        name="my_model_grand_child",
        query={"query": "select * from my_model_child union all select * from my_model_child_2", "kind": "HogQLQuery"},
    )
    grand_child_saved_query.columns = await sync_to_async(grand_child_saved_query.get_columns)()
    await grand_child_saved_query.asave()

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

    select = [Selector(label=child_saved_query.id.hex, ancestors="ALL")]
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

    select = [Selector(label=parent_saved_query.id.hex, descendants="ALL")]
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

    select = [
        Selector(label=parent_saved_query.id.hex),
        Selector(label=child_saved_query.id.hex),
        Selector(label=child_2_saved_query.id.hex),
    ]
    inputs = BuildDagActivityInputs(team_id=ateam.pk, select=select)

    async with asyncio.timeout(10):
        dag = await activity_environment.run(build_dag_activity, inputs)

    assert len(dag) == 5
    assert dag[parent_saved_query.id.hex].children == {child_saved_query.id.hex, child_2_saved_query.id.hex}

    assert dag[child_saved_query.id.hex].parents == {parent_saved_query.id.hex}
    assert dag[child_2_saved_query.id.hex].parents == {parent_saved_query.id.hex}

    selected = tuple(selected.label for selected in select)
    assert all(dag[selected].selected is True for selected in selected)
    assert all(dag[other].selected is False for other in dag.keys() if other not in selected)


async def test_build_dag_activity_select_first_parents(activity_environment, ateam, saved_queries):
    """Test the build dag activity with a sample set of models.

    In this test we attempt to select first parents of a model using a '1+' prefix.
    """
    _, child_saved_query, child_2_saved_query, grand_child_saved_query = saved_queries

    select = [Selector(label=grand_child_saved_query.id.hex, ancestors=1)]
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

    select = [Selector(label=parent_saved_query.id.hex, descendants=1)]
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

    select = [Selector(label=child_saved_query.id.hex, descendants=1, ancestors=1)]
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
    inputs = RunWorkflowInputs(
        team_id=ateam.pk,
        select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0) for saved_query in saved_queries],
    )

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        freeze_time(TEST_TIME),
    ):
        async with temporalio.worker.Worker(
            temporal_client,
            task_queue=settings.DATA_MODELING_TASK_QUEUE,
            workflows=[RunWorkflow],
            activities=[
                start_run_activity,
                build_dag_activity,
                run_dag_activity,
                finish_run_activity,
                create_job_model_activity,
                fail_jobs_activity,
                cleanup_running_jobs_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # Ensure the team exists in the DB context before running workflow
            await database_sync_to_async(Team.objects.get)(pk=ateam.pk)
            await temporal_client.execute_workflow(
                RunWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )

            tables_and_queries = {}

            for query in saved_queries:
                await database_sync_to_async(query.refresh_from_db)()

                delta_table = deltalake.DeltaTable(
                    table_uri=f"s3://{bucket_name}/team_{ateam.pk}_model_{query.id.hex}/modeling/{query.normalized_name}",
                    storage_options={
                        "aws_access_key_id": str(settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY),
                        "aws_secret_access_key": str(settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET),
                        "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                        "region_name": str(settings.DATAWAREHOUSE_LOCAL_BUCKET_REGION),
                        "AWS_ALLOW_HTTP": "true",
                        "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
                    },
                )

                # All test tables have the same columns, which is a limitation of our test
                table = delta_table.to_pyarrow_table(columns=["event", "distinct_id", "timestamp"])
                tables_and_queries[query.normalized_name] = (table, query)

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
                assert key == query.normalized_name

                sorted_rows = sorted(table.to_pylist(), key=lambda d: (d["distinct_id"], d["timestamp"]))
                for index, row in enumerate(sorted_rows):
                    # Hack:
                    # There's some drift in microseconds of the datetimes, the pyarrow
                    # tabls is rounding the microseconds to the nearest 100,000
                    row["timestamp"] = row["timestamp"].replace(microsecond=0)
                    expected_data[index]["timestamp"] = expected_data[index]["timestamp"].replace(microsecond=0)
                    assert row == expected_data[index]

                assert query.status == DataWarehouseSavedQuery.Status.COMPLETED
                assert query.last_run_at == TEST_TIME
                assert query.is_materialized is True

                # Verify row count was updated in the DataWarehouseTable
                warehouse_table = await DataWarehouseTable.objects.aget(team_id=ateam.pk, id=query.table_id)
                assert warehouse_table is not None, f"DataWarehouseTable for {query.name} not found"
                # Match the 50 page_view events defined above
                assert warehouse_table.row_count == len(expected_data), (
                    f"Row count for {query.name} not the expected value"
                )
                assert warehouse_table.size_in_s3_mib is not None and warehouse_table.size_in_s3_mib != 0, (
                    f"Table size in mib for {query.name} is not set"
                )
                assert warehouse_table.credential_id is None, "Table has credentials set when it shouldn't"

            job = await DataModelingJob.objects.aget(workflow_id=workflow_id)
            assert job.storage_delta_mib is not None and job.storage_delta_mib != 0, f"Job storage delta is not set"


async def test_run_workflow_with_minio_bucket_with_errors(
    minio_client,
    ateam,
    bucket_name,
    pageview_events,
    saved_queries,
    temporal_client,
):
    workflow_id = str(uuid.uuid4())
    inputs = RunWorkflowInputs(
        team_id=ateam.pk,
        select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0) for saved_query in saved_queries],
    )

    async def mock_materialize_model(model_label, team, saved_query, job):
        raise Exception("testing exception")

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        freeze_time(TEST_TIME),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.materialize_model", mock_materialize_model),
    ):
        async with temporalio.worker.Worker(
            temporal_client,
            task_queue=settings.DATA_MODELING_TASK_QUEUE,
            workflows=[RunWorkflow],
            activities=[
                start_run_activity,
                build_dag_activity,
                run_dag_activity,
                finish_run_activity,
                create_job_model_activity,
                fail_jobs_activity,
                cleanup_running_jobs_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # Ensure the team exists in the DB context before running workflow
            await database_sync_to_async(Team.objects.get)(pk=ateam.pk)
            await temporal_client.execute_workflow(
                RunWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )

    job = await DataModelingJob.objects.aget(workflow_id=workflow_id)
    assert job is not None
    assert job.status == DataModelingJob.Status.FAILED


async def test_run_workflow_revert_materialization(
    minio_client,
    ateam,
    bucket_name,
    pageview_events,
    saved_queries,
    temporal_client,
):
    workflow_id = str(uuid.uuid4())
    inputs = RunWorkflowInputs(team_id=ateam.pk)

    def mock_hogql_table(_query, _team, _logger):
        raise Exception("Unknown table")

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        freeze_time(TEST_TIME),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table),
    ):
        async with temporalio.worker.Worker(
            temporal_client,
            task_queue=settings.DATA_MODELING_TASK_QUEUE,
            workflows=[RunWorkflow],
            activities=[
                start_run_activity,
                build_dag_activity,
                run_dag_activity,
                finish_run_activity,
                create_job_model_activity,
                fail_jobs_activity,
                cleanup_running_jobs_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # Ensure the team exists in the DB context before running workflow
            await database_sync_to_async(Team.objects.get)(pk=ateam.pk)
            await temporal_client.execute_workflow(
                RunWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )

    job = await DataModelingJob.objects.aget(workflow_id=workflow_id)
    assert job is not None
    assert job.status == DataModelingJob.Status.FAILED

    for query in saved_queries:
        await database_sync_to_async(query.refresh_from_db)()
        assert query.is_materialized is False


async def test_run_workflow_timeout_exceeded(
    minio_client,
    ateam,
    bucket_name,
    pageview_events,
    saved_queries,
    temporal_client,
):
    workflow_id = str(uuid.uuid4())
    inputs = RunWorkflowInputs(team_id=ateam.pk)

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        freeze_time(TEST_TIME),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table") as mock_hogql_table,
        unittest.mock.patch(
            "posthog.temporal.data_modeling.run_workflow.a_pause_saved_query_schedule"
        ) as mock_pause_saved_query_schedule,
    ):
        mock_hogql_table.side_effect = Exception(
            "Code: 159. DB::Exception: Timeout exceeded: elapsed 600585.167566 ms, maximum: 600000 ms. (TIMEOUT_EXCEEDED) (version 25.8.12.129 (official build))"
        )

        async with temporalio.worker.Worker(
            temporal_client,
            task_queue=settings.DATA_MODELING_TASK_QUEUE,
            workflows=[RunWorkflow],
            activities=[
                start_run_activity,
                build_dag_activity,
                run_dag_activity,
                finish_run_activity,
                create_job_model_activity,
                fail_jobs_activity,
                cleanup_running_jobs_activity,
            ],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # Ensure the team exists in the DB context before running workflow
            await database_sync_to_async(Team.objects.get)(pk=ateam.pk)
            await temporal_client.execute_workflow(
                RunWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.DATA_MODELING_TASK_QUEUE,
                retry_policy=temporalio.common.RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=30),
            )

    # Temporal shouldn't reattempt the activity
    assert mock_hogql_table.call_count == 1
    mock_pause_saved_query_schedule.assert_called()

    job = await DataModelingJob.objects.aget(workflow_id=workflow_id)
    assert job is not None
    assert job.status == DataModelingJob.Status.FAILED

    for query in saved_queries:
        await database_sync_to_async(query.refresh_from_db)()
        assert query.is_materialized is False
        assert query.sync_frequency_interval is None


async def test_run_workflow_triggers_ducklake_copy_child(monkeypatch):
    model_label = "model-under-test"
    ducklake_model = DuckLakeCopyModelInput(
        model_label=model_label,
        saved_query_id=str(uuid.uuid4()),
        table_uri="s3://source/table",
    )

    @temporal_activity.defn
    async def cleanup_stub(inputs):
        return None

    @temporal_activity.defn
    async def create_job_stub(inputs):
        return "job-child"

    @temporal_activity.defn
    async def build_dag_stub(inputs) -> run_workflow_module.DAG:
        return {model_label: ModelNode(label=model_label, selected=True)}

    @temporal_activity.defn
    async def start_run_stub(inputs):
        return None

    @temporal_activity.defn
    async def run_dag_stub(inputs):
        return run_workflow_module.Results(
            completed={model_label},
            failed=set(),
            ancestor_failed=set(),
            ducklake_models=[ducklake_model],
        )

    @temporal_activity.defn
    async def finish_run_stub(inputs):
        return None

    @temporal_activity.defn
    async def fail_jobs_stub(inputs):
        return None

    monkeypatch.setattr(run_workflow_module, "cleanup_running_jobs_activity", cleanup_stub)
    monkeypatch.setattr(run_workflow_module, "create_job_model_activity", create_job_stub)
    monkeypatch.setattr(run_workflow_module, "build_dag_activity", build_dag_stub)
    monkeypatch.setattr(run_workflow_module, "start_run_activity", start_run_stub)
    monkeypatch.setattr(run_workflow_module, "run_dag_activity", run_dag_stub)
    monkeypatch.setattr(run_workflow_module, "finish_run_activity", finish_run_stub)
    monkeypatch.setattr(run_workflow_module, "fail_jobs_activity", fail_jobs_stub)

    with override_settings(DUCKLAKE_TASK_QUEUE="ducklake-test"):
        child_ducklake_workflow_runs.clear()
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with temporalio.worker.Worker(
                env.client,
                task_queue="ducklake-test",
                workflows=[RunWorkflow, DummyDuckLakeCopyDataModelingWorkflow],
                activities=[
                    cleanup_stub,
                    create_job_stub,
                    build_dag_stub,
                    start_run_stub,
                    run_dag_stub,
                    finish_run_stub,
                    fail_jobs_stub,
                ],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    RunWorkflow.run,
                    RunWorkflowInputs(team_id=1),
                    id=str(uuid.uuid4()),
                    task_queue="ducklake-test",
                    execution_timeout=dt.timedelta(seconds=30),
                )

    assert len(child_ducklake_workflow_runs) == 1
    assert child_ducklake_workflow_runs[0]["team_id"] == 1
    assert child_ducklake_workflow_runs[0]["models"][0]["model_label"] == model_label


async def test_dlt_direct_naming(ateam, bucket_name, minio_client, pageview_events):
    """Test that setting SCHEMA__NAMING=direct preserves original column casing when materializing models."""
    # Query with CamelCase and PascalCase column names, not snake_case
    query = """\
    select
      event as Event,
      if(distinct_id != '0', distinct_id, null) as DistinctId,
      timestamp as TimeStamp,
      'example' as CamelCaseColumn
    from events
    where event = '$pageview'
    """
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="camel_case_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    # Make sure we have pageview events for the query to work with
    events, _ = pageview_events

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch.dict(os.environ, {"SCHEMA__NAMING": "direct"}, clear=True),
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        # Check that SCHEMA__NAMING is set to direct in the environment
        assert os.environ.get("SCHEMA__NAMING") == "direct", "SCHEMA__NAMING should be 'direct'"

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

    await database_sync_to_async(saved_query.refresh_from_db)()
    assert saved_query.is_materialized is True

    # Check that the column names maintain their original casing
    table_columns = delta_table.to_pyarrow_table().column_names
    # Verify the original capitalization is preserved
    assert "Event" in table_columns, "Column 'Event' should maintain its original capitalization"
    assert "DistinctId" in table_columns, "Column 'DistinctId' should maintain its original capitalization"
    assert "TimeStamp" in table_columns, "Column 'TimeStamp' should maintain its original capitalization"
    assert "CamelCaseColumn" in table_columns, "Column 'CamelCaseColumn' should maintain its original capitalization"


async def test_materialize_model_with_decimal256_fix(ateam, bucket_name, minio_client):
    """Test that materialize_model successfully transforms Decimal256 types to float since decimal128 is not precise enough."""
    query = "SELECT 1 as test_column FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="decimal_fix_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    def mock_hogql_table(*args, **kwargs):
        from decimal import Decimal

        high_precision_decimal_type = pa.decimal256(76, 32)
        problematic_data = pa.array(
            [Decimal("12345678901234567890123456789012345678901234.12345678901234567890123456789012")],
            type=high_precision_decimal_type,
        )

        batch1 = pa.RecordBatch.from_arrays(
            [problematic_data, pa.array([1], type=pa.int64())], names=["high_precision_decimal", "regular_column"]
        )

        async def async_generator():
            yield batch1, [("high_precision_decimal", "Decimal(76, 32)"), ("regular_column", "Int64")]

        return async_generator()

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table),
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "high_precision_decimal" in table.column_names
        assert "regular_column" in table.column_names

        high_precision_column = table.column("high_precision_decimal")
        # Should be Decimal128 with reduced precision, not float64
        assert pa.types.is_decimal(high_precision_column.type)
        assert isinstance(high_precision_column.type, pa.Decimal128Type)
        assert high_precision_column.type.precision == 38
        assert high_precision_column.type.scale == 37

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED

        await database_sync_to_async(saved_query.refresh_from_db)()
        assert saved_query.is_materialized is True


async def test_materialize_model_with_decimal256_downscale_to_decimal128(ateam, bucket_name, minio_client):
    """Test that materialize_model successfully downscales Decimal256 to Decimal128 when the value fits."""
    query = "SELECT 1 as test_column FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="decimal_downscale_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    def mock_hogql_table(*args, **kwargs):
        from decimal import Decimal

        high_precision_decimal_type = pa.decimal256(50, 10)
        manageable_data = pa.array(
            [Decimal("1234567890123456789012345678.1234567890")],
            type=high_precision_decimal_type,
        )

        batch1 = pa.RecordBatch.from_arrays(
            [manageable_data, pa.array([1], type=pa.int64())], names=["manageable_decimal", "regular_column"]
        )

        async def async_generator():
            yield batch1, [("manageable_decimal", "Decimal(50, 10)"), ("regular_column", "Int64")]

        return async_generator()

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table),
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "manageable_decimal" in table.column_names
        assert "regular_column" in table.column_names

        manageable_decimal_column = table.column("manageable_decimal")
        # Should be Decimal128, not float64
        assert pa.types.is_decimal(manageable_decimal_column.type)
        assert isinstance(manageable_decimal_column.type, pa.Decimal128Type)
        assert manageable_decimal_column.type.precision == 38
        assert manageable_decimal_column.type.scale == 10

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED

        await database_sync_to_async(saved_query.refresh_from_db)()
        assert saved_query.is_materialized is True


async def test_cleanup_running_jobs_activity(activity_environment, ateam):
    """Test cleanup marks all existing RUNNING jobs as FAILED when starting a new run."""
    old_job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam, status=DataModelingJob.Status.RUNNING, workflow_id="old-1", workflow_run_id="run-1"
    )
    recent_job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam, status=DataModelingJob.Status.RUNNING, workflow_id="recent-1", workflow_run_id="run-2"
    )
    completed_job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam, status=DataModelingJob.Status.COMPLETED, workflow_id="completed-1", workflow_run_id="run-3"
    )

    await activity_environment.run(cleanup_running_jobs_activity, CleanupRunningJobsActivityInputs(team_id=ateam.pk))

    await database_sync_to_async(old_job.refresh_from_db)()
    await database_sync_to_async(recent_job.refresh_from_db)()
    await database_sync_to_async(completed_job.refresh_from_db)()

    assert old_job.status == DataModelingJob.Status.FAILED
    assert old_job.error is not None
    assert "Job timed out" in old_job.error
    assert recent_job.status == DataModelingJob.Status.FAILED
    assert recent_job.error is not None
    assert "Job timed out" in recent_job.error
    assert completed_job.status == DataModelingJob.Status.COMPLETED


async def test_create_job_model_activity_cleans_up_running_jobs(activity_environment, ateam, temporal_client):
    """Test that orphaned jobs are cleaned up when running the full workflow."""
    # Create old orphaned job
    orphaned_job = await database_sync_to_async(DataModelingJob.objects.create)(
        team=ateam, status=DataModelingJob.Status.RUNNING, workflow_id="orphaned-1", workflow_run_id="run-1"
    )
    await database_sync_to_async(DataModelingJob.objects.filter(id=orphaned_job.id).update)(
        updated_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    )

    saved_query = await database_sync_to_async(DataWarehouseSavedQuery.objects.create)(
        team=ateam, name="test_query", query={"query": "SELECT * FROM events LIMIT 10", "kind": "HogQLQuery"}
    )

    await activity_environment.run(cleanup_running_jobs_activity, CleanupRunningJobsActivityInputs(team_id=ateam.pk))

    await database_sync_to_async(orphaned_job.refresh_from_db)()
    assert orphaned_job.status == DataModelingJob.Status.FAILED
    assert orphaned_job.error is not None
    assert "Job timed out" in orphaned_job.error

    with unittest.mock.patch("temporalio.activity.info") as mock_info:
        mock_info.return_value.workflow_id = "new-workflow"
        mock_info.return_value.workflow_run_id = "new-run"

        new_job_id = await activity_environment.run(
            create_job_model_activity,
            CreateJobModelInputs(
                team_id=ateam.pk, select=[Selector(label=saved_query.id.hex, ancestors=0, descendants=0)]
            ),
        )

    new_job = await database_sync_to_async(DataModelingJob.objects.get)(id=new_job_id)
    assert new_job.status == DataModelingJob.Status.RUNNING
    assert new_job.workflow_id == "new-workflow"
    assert new_job.workflow_run_id == "new-run"


async def test_materialize_model_progress_tracking(ateam, bucket_name, minio_client):
    """Test that materialize_model tracks progress during S3 writes."""
    query = "SELECT 1 as test_column FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="progress_tracking_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    def mock_hogql_table(*args, **kwargs):
        # Create multiple batches to test progress tracking
        batch1 = pa.RecordBatch.from_arrays([pa.array([1, 2, 3], type=pa.int64())], names=["test_column"])
        batch2 = pa.RecordBatch.from_arrays([pa.array([4, 5], type=pa.int64())], names=["test_column"])
        batch3 = pa.RecordBatch.from_arrays([pa.array([6], type=pa.int64())], names=["test_column"])

        async def async_generator():
            yield batch1, [("test_column", "Int64")]
            yield batch2, [("test_column", "Int64")]
            yield batch3, [("test_column", "Int64")]

        return async_generator()

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.get_query_row_count", return_value=6),
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        # Verify initial state
        assert job.rows_materialized == 0

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        # Verify final state
        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED
        assert job.rows_materialized == 6
        assert job.rows_expected == 6


async def test_materialize_model_with_non_utc_timestamp(ateam, bucket_name, minio_client, truncate_events_table):
    await sync_to_async(bulk_create_events)(
        [{"event": "user signed up", "distinct_id": "1", "team": ateam, "timestamp": "2022-01-01T12:00:00"}]
    )

    query = "SELECT toTimeZone(timestamp, 'US/Samoa') as timestamp FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="timezone_fix_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "timestamp" in table.column_names

        timestamp_column = table.column("timestamp")
        assert pa.types.is_timestamp(timestamp_column.type)

        assert timestamp_column[0].as_py() == dt.datetime(2022, 1, 1, 12, 0, tzinfo=dt.UTC)

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED


async def test_materialize_model_with_utc_timestamp(ateam, bucket_name, minio_client, truncate_events_table):
    await sync_to_async(bulk_create_events)(
        [{"event": "user signed up", "distinct_id": "1", "team": ateam, "timestamp": "2022-01-01T00:00:00"}]
    )

    query = "SELECT toTimeZone(timestamp, 'UTC') as timestamp FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="timezone_fix_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "timestamp" in table.column_names

        timestamp_column = table.column("timestamp")
        assert pa.types.is_timestamp(timestamp_column.type)

        assert timestamp_column[0].as_py() == dt.datetime(2022, 1, 1, 0, 0, tzinfo=dt.UTC)

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED


async def test_materialize_model_with_date(ateam, bucket_name, minio_client, truncate_events_table):
    await sync_to_async(bulk_create_events)(
        [{"event": "user signed up", "distinct_id": "1", "team": ateam, "timestamp": "2022-01-01T12:00:00"}]
    )

    query = "SELECT toStartOfMonth(timestamp) as timestamp FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="timezone_fix_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "timestamp" in table.column_names

        timestamp_column = table.column("timestamp")
        assert pa.types.is_date(timestamp_column.type)

        assert timestamp_column[0].as_py() == dt.date(2022, 1, 1)

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED


async def test_materialize_model_with_plain_datetime(ateam, bucket_name, minio_client, truncate_events_table):
    await sync_to_async(bulk_create_events)(
        [{"event": "user signed up", "distinct_id": "1", "team": ateam, "timestamp": "2022-01-01T12:00:00"}]
    )

    query = "SELECT toDateTime(timestamp) as timestamp FROM events LIMIT 1"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="timezone_fix_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    with override_settings(
        BUCKET_URL=f"s3://{bucket_name}",
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        key, delta_table, job_id = await materialize_model(
            saved_query.id.hex,
            ateam,
            saved_query,
            job,
            unittest.mock.AsyncMock(),
        )

        assert key == saved_query.normalized_name

        table = delta_table.to_pyarrow_table()
        assert table.num_rows == 1
        assert "timestamp" in table.column_names

        timestamp_column = table.column("timestamp")
        assert pa.types.is_timestamp(timestamp_column.type)

        assert timestamp_column[0].as_py() == dt.datetime(2022, 1, 1, 12, 0, tzinfo=dt.UTC)

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.COMPLETED


async def test_materialize_model_empty_results(ateam, bucket_name, minio_client):
    """Test that materialize_model raises NonRetryableException when query returns no results."""
    query = "SELECT 1 WHERE 1 = 0"
    saved_query = await DataWarehouseSavedQuery.objects.acreate(
        team=ateam,
        name="empty_results_test_model",
        query={"query": query, "kind": "HogQLQuery"},
    )

    async def mock_hogql_table(*args, **kwargs):
        return
        yield  # makes this a generator but nothing is ever yielded because of the return

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.hogql_table", mock_hogql_table),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.get_query_row_count", return_value=0),
        unittest.mock.patch("posthog.temporal.data_modeling.run_workflow.a_pause_saved_query_schedule"),
    ):
        job = await database_sync_to_async(DataModelingJob.objects.create)(
            team=ateam,
            status=DataModelingJob.Status.RUNNING,
            workflow_id="test_workflow",
        )

        with pytest.raises(NonRetryableException) as exc_info:
            await materialize_model(
                saved_query.id.hex,
                ateam,
                saved_query,
                job,
                unittest.mock.AsyncMock(),
            )

        assert "returned no results" in str(exc_info.value)

        await database_sync_to_async(job.refresh_from_db)()
        assert job.status == DataModelingJob.Status.FAILED
        assert job.error is not None
        assert "returned no results" in job.error

        await database_sync_to_async(saved_query.refresh_from_db)()
        assert saved_query.latest_error is not None
        assert "returned no results" in saved_query.latest_error


child_ducklake_workflow_runs: list[dict] = []


@temporal_workflow.defn(name="ducklake-copy.data-modeling")
class DummyDuckLakeCopyDataModelingWorkflow:
    @temporal_workflow.run
    async def run(self, inputs: dict) -> None:
        child_ducklake_workflow_runs.append(inputs)
