import re
import json
import uuid
import functools
import contextlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional, cast
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest import mock
from unittest.mock import AsyncMock

from django.conf import settings
from django.test import override_settings

import s3fs
import orjson
import psycopg
import pyarrow as pa
import aioboto3
import deltalake
import pytest_asyncio
import pyarrow.parquet as pq
import posthoganalytics
from asgiref.sync import sync_to_async
from deltalake import DeltaTable
from dlt.common.configuration.specs.aws_credentials import AwsCredentials
from dlt.sources.helpers.rest_client.client import RESTClient
from stripe import ListObject
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    EventsNode,
    FunnelsQuery,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
)

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.funnels.funnel import FunnelUDF
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.team.team import Team
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError
from posthog.temporal.ducklake import ACTIVITIES as DUCKLAKE_ACTIVITIES
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import DuckLakeCopyDataImportsWorkflow
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.facade.api import WebhookConsumerConfig, WebhookS3Sink
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    get_latest_run_if_exists,
)
from products.warehouse_sources.backend.models.external_table_definitions import external_tables
from products.warehouse_sources.backend.temporal.data_imports.cdp_producer_job import CDPProducerJobWorkflow
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    process_message,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import get_rows
from products.warehouse_sources.backend.temporal.data_imports.settings import ACTIVITIES
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient as PostHogRESTClient,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import XminBounds
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    BALANCE_TRANSACTION_RESOURCE_NAME as STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME as STRIPE_CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME as STRIPE_CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME as STRIPE_CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME as STRIPE_DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME as STRIPE_INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME as STRIPE_PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME as STRIPE_PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME as STRIPE_REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    ExternalDataSourceType,
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)

BUCKET_NAME = "test-pipeline"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)

_current_pipeline_mode = "non_dlt"


@pytest.fixture(params=["non_dlt", "v3"], autouse=True)
def pipeline_mode(request, _clean_sourcebatch_tables):
    global _current_pipeline_mode
    _current_pipeline_mode = request.param
    yield request.param
    _current_pipeline_mode = "non_dlt"


# TODO: remove _KafkaMessageCapture once Postgres producer is fully validated
# class _KafkaMessageCapture:
#     ...
# _kafka_capture = _KafkaMessageCapture()


def _get_test_database_url() -> str:
    """Build a psycopg-compatible DSN from Django's active test database connection."""
    from django.db import connection

    s = connection.settings_dict
    host = s.get("HOST", "localhost") or "localhost"
    port = s.get("PORT", "5432") or "5432"
    return f"postgres://{s['USER']}:{s['PASSWORD']}@{host}:{port}/{s['NAME']}"


class _PostgresQueueReplay:
    """Reads batch rows written by PostgresProducer during tests and replays them
    through process_message(), mimicking what the real BatchConsumer does."""

    def __init__(self) -> None:
        self._processed_batches: set[tuple[str, int]] = set()

    def replay_batches_for_run(self, run_uuid: str) -> None:
        from django.db import connection as django_conn

        with django_conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, team_id, schema_id, source_id, job_id, run_uuid,
                       batch_index, s3_path, row_count, byte_size, is_final_batch,
                       total_batches, total_rows, sync_type, cumulative_row_count,
                       resource_name, is_resume, is_first_ever_sync, metadata
                FROM {BATCH_TABLE}
                WHERE run_uuid = %s
                ORDER BY created_at ASC, batch_index ASC
                """,
                [run_uuid],
            )
            columns = [col.name for col in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        if not rows:
            return

        for row in rows:
            if isinstance(row.get("metadata"), str):
                row["metadata"] = json.loads(row["metadata"])
            batch = PendingBatch(latest_attempt=0, **row)
            try:
                process_message(batch.to_export_signal())
            except Exception:
                pass

    def get_run_uuids_for_job(self, job_id: str) -> list[str]:
        from django.db import connection as django_conn

        with django_conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT run_uuid FROM {BATCH_TABLE} WHERE job_id = %s ORDER BY run_uuid",
                [job_id],
            )
            return [row[0] for row in cur.fetchall()]

    def mock_idempotency_check(
        self,
        team_id: int,
        schema_id: str,
        run_uuid: str,
        batch_index: int,
        delta_table_helper: Any = None,
    ) -> bool:
        key = (run_uuid, batch_index)
        if key in self._processed_batches:
            return True
        self._processed_batches.add(key)
        return False

    def clear(self) -> None:
        self._processed_batches.clear()


_pg_queue_replay = _PostgresQueueReplay()


@pytest.fixture
def postgres_config():
    return {
        "user": settings.PG_USER,
        "password": settings.PG_PASSWORD,
        "database": "external_data_database",
        "schema": "external_data_schema",
        "host": settings.PG_HOST,
        "port": int(settings.PG_PORT),
    }


@pytest_asyncio.fixture
async def postgres_connection(postgres_config, setup_postgres_test_db):
    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )

    yield connection

    await connection.close()


# `mysql_container`, `mysql_config`, and `mysql_connection` live in
# conftest.py so the container starts once per test session and is shared
# across every test file in this package.


def _mysql_job_inputs(mysql_config: dict) -> dict[str, str | dict[str, str]]:
    """Serialize `mysql_config` into the flat string-keyed dict the
    ExternalDataSource.job_inputs pipeline expects (same shape the UI
    produces).

    Return type matches `_run`'s `job_inputs` param — dicts are invariant
    so the wider `str | dict[str, str]` value type is required even
    though every value this helper produces is a plain `str`.
    """
    return {
        "host": mysql_config["host"],
        "port": str(mysql_config["port"]),
        "database": mysql_config["database"],
        "user": mysql_config["user"],
        "password": mysql_config["password"],
        "schema": mysql_config["schema"],
        "using_ssl": "false",
    }


@pytest.fixture
def mock_paddle_client():
    response_data: dict[str, Any] = {"items": []}

    class MockResponse:
        def __init__(self, json_data):
            self.json_data = json_data
            self.status_code = 200

        def json(self):
            return self.json_data

        def raise_for_status(self):
            pass

    def set_response(items: Any) -> None:
        response_data["items"] = items

    def mock_paddle_request(
        session: Any,
        method: str,
        url: str,
        headers: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        **kwargs,
    ):
        return MockResponse(
            {
                "data": response_data["items"],
                "meta": {"pagination": {"next": None}},
            }
        )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.paddle_request",
            side_effect=mock_paddle_request,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.paddle.paddle.validate_credentials",
            return_value=True,
        ),
    ):
        yield set_response


@pytest.fixture
def mock_customer_io_client():
    """Mock the Customer.io App API session inside `api_client`.

    The Customer.io source skips the REST framework patched by `_execute_run`
    and talks to the App API through a tracked `requests.Session` returned by
    `_session(api_key)`. We patch that helper to return a stub session whose
    `.get(...)` yields a canned payload.
    """
    response_data: dict[str, Any] = {"payload": {}}

    class MockResponse:
        def __init__(self, json_data: dict):
            self.json_data = json_data
            self.status_code = 200

        def json(self):
            return self.json_data

        def raise_for_status(self):
            pass

    class _StubSession:
        def get(self, *args, **kwargs):
            return MockResponse(response_data["payload"])

    def set_response(payload: dict) -> None:
        response_data["payload"] = payload

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.api_client._session",
            return_value=_StubSession(),
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.customer_io.api_client.validate_credentials",
            return_value=(True, None),
        ),
    ):
        yield set_response


@pytest_asyncio.fixture(autouse=True)
async def minio_client():
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
            await minio_client.head_bucket(Bucket=BUCKET_NAME)
        except:
            await minio_client.create_bucket(Bucket=BUCKET_NAME)

        yield minio_client


async def _run(
    team: Team,
    schema_name: str,
    table_name: str,
    source_type: str,
    job_inputs: dict[str, str | dict[str, str]],
    mock_data_response: Any,
    sync_type: Optional[ExternalDataSchema.SyncType] = None,
    sync_type_config: Optional[dict] = None,
    billable: Optional[bool] = None,
    ignore_assertions: Optional[bool] = False,
):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type=source_type,
        job_inputs=job_inputs,
    )
    source.created_at = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
    await sync_to_async(source.save)()

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=schema_name,
        team_id=team.pk,
        source_id=source.pk,
        sync_type=sync_type,
        sync_type_config=sync_type_config or {},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=billable if billable is not None else True,
    )

    with (
        mock.patch.object(DeltaTableHelper, "compact_table") as mock_compact_table,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_data_import_finished_metric"
        ) as mock_get_data_import_finished_metric,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.metrics.get_producer"
        ) as mock_app_metrics_producer_cls,
    ):
        await _execute_run(workflow_id, inputs, mock_data_response)

        # In v3 mode, the job is still RUNNING after the workflow (consumer marks it COMPLETED),
        # so we need to query without status filter to get the job_id for the replay.
        run_for_replay = await sync_to_async(
            ExternalDataJob.objects.filter(team_id=team.pk, pipeline_id=source.pk).order_by("-created_at").first
        )()
        await _replay_v3_consumer(
            team_id=team.pk,
            schema_id=schema.id,
            job_id=str(run_for_replay.id) if run_for_replay else None,
        )

    if not ignore_assertions:
        run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=source.pk)
        assert run is not None
        assert run.status == ExternalDataJob.Status.COMPLETED
        assert run.finished_at is not None
        assert run.storage_delta_mib is not None
        assert run.storage_delta_mib != 0

        mock_compact_table.assert_called()
        mock_get_data_import_finished_metric.assert_called_with(
            source_type=source_type, status=ExternalDataJob.Status.COMPLETED.lower()
        )

        # Assert that app_metrics2 rows were emitted for the successful job — both
        # the success row and the rows_synced row (since a successful e2e run writes
        # at least one row). Pin both V3 (consumer-side) and NonDLT (workflow-side)
        # paths so a regression in either gates here.
        assert run.rows_synced is not None and run.rows_synced > 0, (
            f"expected run.rows_synced to be a positive number, got {run.rows_synced}"
        )
        produce_calls = mock_app_metrics_producer_cls.return_value.produce.call_args_list
        emitted_payloads = [call.kwargs["data"] for call in produce_calls]
        status_rows = [
            p for p in emitted_payloads if p["app_source_id"] == str(source.pk) and p["metric_kind"] == "success"
        ]
        rows_rows = [p for p in emitted_payloads if p["app_source_id"] == str(source.pk) and p["metric_kind"] == "rows"]
        assert len(status_rows) == 1, f"expected one success row, got {emitted_payloads}"
        assert status_rows[0]["app_source"] == "warehouse_source_sync"
        assert status_rows[0]["metric_name"] == "succeeded"
        assert status_rows[0]["count"] == 1
        assert status_rows[0]["instance_id"] == str(schema.id)
        assert status_rows[0]["team_id"] == team.pk
        assert status_rows[0]["timestamp"] == format_clickhouse_timestamp(run.finished_at)
        assert len(rows_rows) == 1, f"expected one rows_synced row, got {emitted_payloads}"
        assert rows_rows[0]["metric_name"] == "rows_synced"
        assert rows_rows[0]["count"] == run.rows_synced, (
            f"rows_synced metric count should match run.rows_synced ({run.rows_synced}); "
            f"got {rows_rows[0]['count']} — likely indicates rows_synced was clobbered by "
            f"update_external_job_status's full-model save() racing with update_job_row_count"
        )
        assert rows_rows[0]["count"] > 0, f"rows_synced metric count should be positive, got {rows_rows[0]['count']}"
        assert rows_rows[0]["app_source"] == "warehouse_source_sync"
        assert rows_rows[0]["team_id"] == team.pk
        assert rows_rows[0]["instance_id"] == str(schema.id)
        assert rows_rows[0]["timestamp"] == status_rows[0]["timestamp"]

        await sync_to_async(schema.refresh_from_db)()

        assert schema.last_synced_at == run.created_at
        assert schema.initial_sync_complete is True

        res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM {table_name}", team)
        assert len(res.results) == 1

        for name, field in external_tables.get(table_name, {}).items():
            if field.hidden:
                continue
            assert name in (res.columns or [])

        await sync_to_async(schema.refresh_from_db)()
        assert schema.sync_type_config.get("reset_pipeline", None) is None

        table: DataWarehouseTable | None = await sync_to_async(lambda: schema.table)()
        assert table is not None
        assert table.size_in_s3_mib is not None
        assert table.queryable_folder is not None
        assert table.credential_id is None

        query_folder_pattern = re.compile(r"^.+?\_\_query\_\d+$")
        assert query_folder_pattern.match(table.queryable_folder)

    return workflow_id, inputs


async def _replay_v3_consumer(team_id: int, schema_id, job_id: str | None = None):
    if _current_pipeline_mode != "v3":
        return

    if not job_id:
        job = await sync_to_async(
            ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id).order_by("-created_at").first
        )()
        if not job:
            return
        job_id = str(job.id)
    else:
        job = await sync_to_async(ExternalDataJob.objects.get)(id=job_id)

    # If the workflow already marked the job as COMPLETED (e.g. worker shutdown scenario),
    # the consumer should not replay — the workflow managed the job status itself and
    # S3 files may have been cleaned up.
    if job.status == ExternalDataJob.Status.COMPLETED:
        _pg_queue_replay.clear()
        return

    run_uuids = await sync_to_async(_pg_queue_replay.get_run_uuids_for_job)(job_id)
    if not run_uuids:
        _pg_queue_replay.clear()
        return

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
            DATA_WAREHOUSE_REDIS_HOST="localhost",
            DATA_WAREHOUSE_REDIS_PORT="6379",
            DATAWAREHOUSE_BUCKET=BUCKET_NAME,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.is_batch_already_processed",
            side_effect=_pg_queue_replay.mock_idempotency_check,
        ),
    ):
        for run_uuid in run_uuids:
            await sync_to_async(_pg_queue_replay.replay_batches_for_run)(run_uuid)

        await sync_to_async(calculate_table_size_activity)(
            CalculateTableSizeActivityInputs(
                team_id=team_id,
                schema_id=str(schema_id),
                job_id=job_id,
            )
        )

    _pg_queue_replay.clear()


async def _execute_run(workflow_id: str, inputs: ExternalDataWorkflowInputs, mock_data_response):
    def mock_paginate(
        class_self,
        path: str = "",
        method: Any = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        auth: Optional[Any] = None,
        paginator: Optional[Any] = None,
        data_selector: Optional[Any] = None,
        hooks: Optional[Any] = None,
        resume_hook: Optional[Any] = None,
        initial_paginator_state: Optional[dict[str, Any]] = None,
    ):
        return iter(mock_data_response)

    def mock_paginate_pages(
        class_self,
        path: str = "",
        method: Any = "GET",
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        auth: Optional[Any] = None,
        paginator: Optional[Any] = None,
        data_selector: Optional[Any] = None,
        hooks: Optional[Any] = None,
        resume_hook: Optional[Any] = None,
        initial_paginator_state: Optional[dict[str, Any]] = None,
    ):
        # Yield each record as its own page so tests that probe chunking
        # by record size still see one call per record.
        return iter([[item] for item in mock_data_response])

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

    _pg_queue_replay.clear()

    with (
        mock.patch.object(RESTClient, "paginate", mock_paginate),
        mock.patch.object(PostHogRESTClient, "paginate", mock_paginate_pages),
        mock.patch.object(ListObject, "auto_paging_iter", return_value=iter(mock_data_response)),
        mock.patch.object(InvoiceListWithAllLines, "auto_paging_iter", return_value=iter(mock_data_response)),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
            DATA_WAREHOUSE_REDIS_HOST="localhost",
            DATA_WAREHOUSE_REDIS_PORT="6379",
            DATAWAREHOUSE_BUCKET=BUCKET_NAME,
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
        contextlib.ExitStack() as stack,
    ):
        if _current_pipeline_mode == "v3":
            stack.enter_context(
                mock.patch(
                    "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock.is_pipeline_v3_enabled",
                    return_value=True,
                )
            )
            # Point the Postgres producer at the Django test database
            stack.enter_context(
                mock.patch(
                    "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline.WAREHOUSE_SOURCES_DATABASE_URL",
                    _get_test_database_url(),
                )
            )
        else:
            stack.enter_context(
                mock.patch(
                    "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock.is_pipeline_v3_enabled",
                    return_value=False,
                )
            )

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow, CDPProducerJobWorkflow, DuckLakeCopyDataImportsWorkflow],
                activities=ACTIVITIES + DUCKLAKE_ACTIVITIES,  # type: ignore
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
                debug_mode=True,  # turn off sandbox/deadlock detector
            ):
                await activity_environment.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )


_STRIPE_JOB_INPUTS: dict[str, str | dict[str, str]] = {
    "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
    "stripe_account_id": "acct_id",
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema_name,table_name,fixture_name",
    [
        (STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME, "stripe_balancetransaction", "stripe_balance_transaction"),
        (STRIPE_CUSTOMER_RESOURCE_NAME, "stripe_customer", "stripe_customer"),
        (STRIPE_INVOICE_RESOURCE_NAME, "stripe_invoice", "stripe_invoice"),
        (STRIPE_PRICE_RESOURCE_NAME, "stripe_price", "stripe_price"),
        (STRIPE_PRODUCT_RESOURCE_NAME, "stripe_product", "stripe_product"),
        (STRIPE_SUBSCRIPTION_RESOURCE_NAME, "stripe_subscription", "stripe_subscription"),
        (STRIPE_DISPUTE_RESOURCE_NAME, "stripe_dispute", "stripe_dispute"),
        (STRIPE_PAYOUT_RESOURCE_NAME, "stripe_payout", "stripe_payout"),
        (STRIPE_REFUND_RESOURCE_NAME, "stripe_refund", "stripe_refund"),
        (STRIPE_INVOICE_ITEM_RESOURCE_NAME, "stripe_invoiceitem", "stripe_invoiceitem"),
        (STRIPE_CREDIT_NOTE_RESOURCE_NAME, "stripe_creditnote", "stripe_credit_note"),
        (
            STRIPE_CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
            "stripe_customerbalancetransaction",
            "stripe_customer_balance_transaction",
        ),
        (
            STRIPE_CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
            "stripe_customerpaymentmethod",
            "stripe_customer_payment_method",
        ),
    ],
)
async def test_stripe_source(team, mock_stripe_client, request, schema_name, table_name, fixture_name):
    fixture_data = request.getfixturevalue(fixture_name)
    await _run(
        team=team,
        schema_name=schema_name,
        table_name=table_name,
        source_type="Stripe",
        job_inputs=_STRIPE_JOB_INPUTS,
        mock_data_response=fixture_data["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_charges(team, stripe_charge, mock_stripe_client):
    # Kept standalone: also asserts that the revenue analytics first-sync
    # notification flag gets set after a successful charges sync.
    await _run(
        team=team,
        schema_name=STRIPE_CHARGE_RESOURCE_NAME,
        table_name="stripe_charge",
        source_type="Stripe",
        job_inputs=_STRIPE_JOB_INPUTS,
        mock_data_response=stripe_charge["data"],
    )

    # Get team from the DB to remove cached config value
    team = await sync_to_async(Team.objects.get)(id=team.id)
    assert team.revenue_analytics_config.notified_first_sync


_ZENDESK_JOB_INPUTS: dict[str, str | dict[str, str]] = {
    "subdomain": "test",
    "api_key": "test_api_key",
    "email_address": "test@posthog.com",
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema_name,table_name,fixture_name,fixture_data_key",
    [
        ("brands", "zendesk_brands", "zendesk_brands", "brands"),
        ("organizations", "zendesk_organizations", "zendesk_organizations", "organizations"),
        ("groups", "zendesk_groups", "zendesk_groups", "groups"),
        ("sla_policies", "zendesk_sla_policies", "zendesk_sla_policies", "sla_policies"),
        ("users", "zendesk_users", "zendesk_users", "users"),
        ("ticket_fields", "zendesk_ticket_fields", "zendesk_ticket_fields", "ticket_fields"),
        ("ticket_events", "zendesk_ticket_events", "zendesk_ticket_events", "ticket_events"),
        ("tickets", "zendesk_tickets", "zendesk_tickets", "tickets"),
        (
            "ticket_metric_events",
            "zendesk_ticket_metric_events",
            "zendesk_ticket_metric_events",
            "ticket_metric_events",
        ),
    ],
)
async def test_zendesk_source(team, request, schema_name, table_name, fixture_name, fixture_data_key):
    fixture_data = request.getfixturevalue(fixture_name)
    await _run(
        team=team,
        schema_name=schema_name,
        table_name=table_name,
        source_type="Zendesk",
        job_inputs=_ZENDESK_JOB_INPUTS,
        mock_data_response=fixture_data[fixture_data_key],
    )


_PADDLE_JOB_INPUTS: dict[str, str | dict[str, str]] = {"paddle_api_key": "test_api_key"}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema_name,table_name,fixture_name",
    [
        ("customers", "paddle_customers", "paddle_customers"),
        ("subscriptions", "paddle_subscriptions", "paddle_subscriptions"),
    ],
)
async def test_paddle_source(team, mock_paddle_client, request, schema_name, table_name, fixture_name):
    fixture_data = request.getfixturevalue(fixture_name)
    mock_paddle_client(fixture_data["data"])
    await _run(
        team=team,
        schema_name=schema_name,
        table_name=table_name,
        source_type="Paddle",
        job_inputs=_PADDLE_JOB_INPUTS,
        mock_data_response=fixture_data["data"],
    )


async def _run_customer_io(team, schema_name, table_name, mock_data, mock_customer_io_client, payload):
    mock_customer_io_client(payload)
    await _run(
        team=team,
        schema_name=schema_name,
        table_name=table_name,
        source_type="CustomerIO",
        job_inputs={"app_api_key": "test-key", "region": "us"},
        mock_data_response=mock_data,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema_name,table_name,fixture_name,fixture_data_key",
    [
        ("broadcasts", "customerio_broadcasts", "customer_io_broadcasts", "broadcasts"),
        ("campaigns", "customerio_campaigns", "customer_io_campaigns", "campaigns"),
        ("collections", "customerio_collections", "customer_io_collections", "collections"),
        ("newsletters", "customerio_newsletters", "customer_io_newsletters", "newsletters"),
        ("object_types", "customerio_object_types", "customer_io_object_types", "types"),
        ("segments", "customerio_segments", "customer_io_segments", "segments"),
        ("sender_identities", "customerio_sender_identities", "customer_io_sender_identities", "sender_identities"),
        ("snippets", "customerio_snippets", "customer_io_snippets", "snippets"),
        ("subscription_topics", "customerio_subscription_topics", "customer_io_subscription_topics", "topics"),
        ("transactional", "customerio_transactional", "customer_io_transactional", "messages"),
    ],
)
async def test_customer_io_source(
    team, mock_customer_io_client, request, schema_name, table_name, fixture_name, fixture_data_key
):
    fixture_data = request.getfixturevalue(fixture_name)
    await _run_customer_io(
        team,
        schema_name=schema_name,
        table_name=table_name,
        mock_data=fixture_data[fixture_data_key],
        mock_customer_io_client=mock_customer_io_client,
        payload=fixture_data,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_chargebee_customer(team, chargebee_customer):
    await _run(
        team=team,
        schema_name="Customers",
        table_name="chargebee_customers",
        source_type="Chargebee",
        job_inputs={"api_key": "test-key", "site_name": "site-test"},
        mock_data_response=[chargebee_customer["list"][0]["customer"]],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reset_pipeline(team, stripe_balance_transaction, mock_stripe_client):
    await _run(
        team=team,
        schema_name="BalanceTransaction",
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_balance_transaction["data"],
        sync_type_config={"reset_pipeline": True},
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_binary_columns(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.binary_col_test (id integer, binary_column bytea)".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.binary_col_test (id, binary_column) VALUES (1, '\x48656C6C6F')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    await _run(
        team=team,
        schema_name="binary_col_test",
        table_name="postgres_binary_col_test",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
    )

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_binary_col_test", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 1
    assert any(x == "id" for x in columns)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_wrapper_files(team, stripe_balance_transaction, mock_stripe_client, minio_client):
    datetime_now = datetime.now(tz=ZoneInfo("UTC"))
    with freeze_time(datetime_now):
        workflow_id, inputs = await _run(
            team=team,
            schema_name="BalanceTransaction",
            table_name="stripe_balancetransaction",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_balance_transaction["data"],
        )

        @sync_to_async
        def get_jobs():
            jobs = ExternalDataJob.objects.filter(
                team_id=team.pk,
                pipeline_id=inputs.external_data_source_id,
            ).order_by("-created_at")

            return list(jobs)

        jobs = await get_jobs()
        latest_job = jobs[0]
        folder_path = await sync_to_async(latest_job.folder_path)()

        s3_objects = await minio_client.list_objects_v2(
            Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_now.timestamp())}/"
        )

        assert len(s3_objects["Contents"]) != 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_funnels_lazy_joins_ordering(team, stripe_customer, mock_stripe_client):
    # Tests that funnels work in PERSON_ID_OVERRIDE_PROPERTIES_JOINED PoE mode when using extended person properties
    await _run(
        team=team,
        schema_name="Customer",
        table_name="stripe_customer",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_customer["data"],
    )

    await sync_to_async(DataWarehouseJoin.objects.create)(
        team=team,
        source_table_name="persons",
        source_table_key="properties.email",
        joining_table_name="stripe_customer",
        joining_table_key="email",
        field_name="stripe_customer",
    )

    query = FunnelsQuery(
        series=[EventsNode(), EventsNode()],
        breakdownFilter=BreakdownFilter(
            breakdown_type=BreakdownType.DATA_WAREHOUSE_PERSON_PROPERTY, breakdown="stripe_customer.email"
        ),
    )
    funnel_class = FunnelUDF(context=FunnelQueryContext(query=query, team=team))

    query_ast = funnel_class.get_query()
    await sync_to_async(execute_hogql_query)(
        query_type="FunnelsQuery",
        query=query_ast,
        team=team,
        modifiers=create_default_modifiers_for_team(
            team, HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED)
        ),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_schema_evolution(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    _workflow_id, inputs = await _run(
        team=team,
        schema_name="test_table",
        table_name="postgres_test_table",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM postgres_test_table", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 1
    assert any(x == "id" for x in columns)

    # Evole schema
    await postgres_connection.execute(
        "ALTER TABLE {schema}.test_table ADD new_col integer".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id, new_col) VALUES (2, 2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    # Execute the same schema again - load
    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM postgres_test_table", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 2
    assert any(x == "id" for x in columns)
    assert any(x == "new_col" for x in columns)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sql_database_missing_incremental_values(team, postgres_config, postgres_connection):
    await postgres_connection.execute("CREATE SCHEMA IF NOT EXISTS {schema}".format(schema=postgres_config["schema"]))
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (null)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    await _run(
        team=team,
        schema_name="test_table",
        table_name="postgres_test_table",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM postgres_test_table", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 1
    assert any(x == "id" for x in columns)

    # Exclude rows that don't have the incremental cursor key set
    assert len(res.results) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sql_database_incremental_initial_value(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    # Setting `id` to `1` - greater than the `integer` incremental initial value of `0`
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    await _run(
        team=team,
        schema_name="test_table",
        table_name="postgres_test_table",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM postgres_test_table", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 1
    assert any(x == "id" for x in columns)

    # Rows with id > initial_value (0) are included
    assert len(res.results) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_billing_limits(team, stripe_customer, mock_stripe_client):
    with freeze_time("2024-01-01T12:00:00Z"):
        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
        )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Customer",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    with mock.patch(
        "ee.billing.quota_limiting.list_limited_team_attributes",
    ) as mock_list_limited_team_attributes:
        mock_list_limited_team_attributes.return_value = [team.api_token]

        await _execute_run(workflow_id, inputs, stripe_customer["data"])

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(team_id=team.id, schema_id=schema.pk)

    assert job.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_customer", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_failure(team, stripe_customer, mock_stripe_client):
    with freeze_time("2024-01-01T12:00:00Z"):
        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
        )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Customer",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    with mock.patch(
        "ee.billing.quota_limiting.list_limited_team_attributes",
    ) as mock_list_limited_team_attributes:
        mock_list_limited_team_attributes.side_effect = Exception("Ruhoh!")

        with pytest.raises(Exception):
            await _execute_run(workflow_id, inputs, stripe_customer["data"])

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(team_id=team.id, schema_id=schema.pk)

    assert job.status == ExternalDataJob.Status.FAILED

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_customer", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_external_job_failure_no_job_model(team, stripe_customer, mock_stripe_client):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Customer",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(team_id=team.id, schema_id=schema.pk)

        return list(jobs)

    with mock.patch.object(
        ExternalDataJob.objects,
        "create",
    ) as create_external_data_job:
        create_external_data_job.side_effect = Exception("Ruhoh!")

        with pytest.raises(Exception):
            await _execute_run(workflow_id, inputs, stripe_customer["data"])

    jobs: list[ExternalDataJob] = await get_jobs()

    assert len(jobs) == 0

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_customer", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_retryable_error(team, zendesk_brands):
    with freeze_time("2024-01-01T12:00:00Z"):
        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Zendesk",
            job_inputs={
                "subdomain": "test",
                "api_key": "test_api_key",
                "email_address": "test@posthog.com",
            },
        )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Brands",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    with (
        mock.patch(
            "ee.billing.quota_limiting.list_limited_team_attributes",
        ) as mock_list_limited_team_attributes,
        mock.patch.object(posthoganalytics, "capture") as capture_mock,
    ):
        mock_list_limited_team_attributes.side_effect = Exception("404 Client Error: Not Found for url")

        with pytest.raises(Exception):
            await _execute_run(workflow_id, inputs, zendesk_brands["brands"])

        capture_mock.assert_called_once()

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(team_id=team.id, schema_id=schema.pk)
    await sync_to_async(schema.refresh_from_db)()

    assert job.status == ExternalDataJob.Status.FAILED
    assert schema.should_sync is False

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM zendesk_brands", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_retryable_error_with_special_characters(team, stripe_customer, mock_stripe_client):
    with freeze_time("2024-01-01T12:00:00Z"):
        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=team,
            status="running",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
        )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="Customer",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    with (
        mock.patch(
            "ee.billing.quota_limiting.list_limited_team_attributes",
        ) as mock_list_limited_team_attributes,
        mock.patch.object(posthoganalytics, "capture") as capture_mock,
    ):
        mock_list_limited_team_attributes.side_effect = Exception(
            "401 Client Error:\nUnauthorized for url: https://api.stripe.com"
        )

        with pytest.raises(Exception):
            await _execute_run(workflow_id, inputs, stripe_customer["data"])

        capture_mock.assert_called_once()

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(team_id=team.id, schema_id=schema.pk)
    await sync_to_async(schema.refresh_from_db)()

    assert job.status == ExternalDataJob.Status.FAILED
    assert schema.should_sync is False

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_customer", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_inconsistent_types_in_data(team):
    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name="organizations",
        team_id=team.pk,
        source_id=source.pk,
        sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        sync_type_config={},
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    await _execute_run(
        workflow_id,
        inputs,
        [
            {
                "id": "4112492",
                "domain_names": "transfer",
                "created_at": "2022-04-25T19:42:18Z",
                "updated_at": "2024-05-31T22:10:48Z",
            },
            {
                "id": "4112492",
                "domain_names": ["transfer", "another_value"],
                "created_at": "2022-04-25T19:42:18Z",
                "updated_at": "2024-05-31T22:10:48Z",
            },
        ],
    )
    await _replay_v3_consumer(team_id=team.pk, schema_id=schema.id)

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM zendesk_organizations", team)
    columns = res.columns
    results = res.results

    assert columns is not None
    assert any(x == "id" for x in columns)
    assert any(x == "domain_names" for x in columns)

    assert results is not None
    assert len(results) == 2

    id_index = columns.index("id")
    arr_index = columns.index("domain_names")

    assert results[0][id_index] == "4112492"
    assert results[0][arr_index] == '["transfer"]'

    assert results[1][id_index] == "4112492"
    assert results[1][arr_index] == '["transfer","another_value"]'


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_uuid_type(team, mock_stripe_client):
    await _run(
        team=team,
        schema_name="BalanceTransaction",
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=[{"id": uuid.uuid4()}],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_decimal_down_scales(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.downsizing_column (id integer, dec_col numeric(10, 2))".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.downsizing_column (id, dec_col) VALUES (1, 12345.60)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.commit()

    workflow_id, inputs = await _run(
        team=team,
        schema_name="downsizing_column",
        table_name="postgres_downsizing_column",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
    )

    await postgres_connection.execute(
        "ALTER TABLE {schema}.downsizing_column ALTER COLUMN dec_col type numeric(9, 2) using dec_col::numeric(9, 2);".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.downsizing_column (id, dec_col) VALUES (1, 1234567.89)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_missing_source(team):
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=uuid.uuid4(),
        external_data_schema_id=uuid.uuid4(),
    )

    with (
        pytest.raises(Exception) as e,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model.delete_external_data_schedule"
        ) as mock_delete_external_data_schedule,
    ):
        await _execute_run(str(uuid.uuid4()), inputs, [])

    exc = cast(Any, e)

    assert exc.value is not None
    assert exc.value.cause is not None
    assert exc.value.cause.cause is not None
    assert exc.value.cause.cause.message is not None

    assert exc.value.cause.cause.message == "Source or schema no longer exists - deleted temporal schedule"

    mock_delete_external_data_schedule.assert_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_nan_numerical_values(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.numerical_nan (id integer, nan_column numeric)".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.numerical_nan (id, nan_column) VALUES (1, 'NaN'::numeric)".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    await _run(
        team=team,
        schema_name="numerical_nan",
        table_name="postgres_numerical_nan",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
    )

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_numerical_nan", team)
    columns = res.columns
    results = res.results

    assert columns is not None
    assert len(columns) == 2
    assert any(x == "id" for x in columns)
    assert any(x == "nan_column" for x in columns)

    assert results is not None
    assert len(results) == 1

    id_index = columns.index("id")
    nan_index = columns.index("nan_column")

    assert results[0][id_index] == 1
    assert results[0][nan_index] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delete_table_on_reset(team, stripe_balance_transaction, mock_stripe_client):
    with (
        mock.patch.object(s3fs.S3FileSystem, "_rm") as mock_s3_delete,
    ):
        workflow_id, inputs = await _run(
            team=team,
            schema_name="BalanceTransaction",
            table_name="stripe_balancetransaction",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_balance_transaction["data"],
            sync_type_config={"reset_pipeline": True},
        )

        schema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)

        assert schema.sync_type_config is not None and isinstance(schema.sync_type_config, dict)
        schema.sync_type_config["reset_pipeline"] = True

        await sync_to_async(schema.save)()

        await _execute_run(str(uuid.uuid4()), inputs, stripe_balance_transaction["data"])

    mock_s3_delete.assert_called()

    await sync_to_async(schema.refresh_from_db)()

    assert schema.sync_type_config is not None and isinstance(schema.sync_type_config, dict)
    assert "reset_pipeline" not in schema.sync_type_config.keys()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_billable_job(team, stripe_balance_transaction, mock_stripe_client):
    workflow_id, inputs = await _run(
        team=team,
        schema_name="BalanceTransaction",
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_balance_transaction["data"],
        billable=False,
    )

    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
    assert run is not None
    assert run.billable is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync(team, postgres_config, postgres_connection, pipeline_mode):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._get_table_chunk_size"
        ) as mock_chunk_size,
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.run_post_load_operations",
            new_callable=AsyncMock,
        ) as mock_v3_post_load,
    ):
        # Set up merge mock chain (needed for v3 where batch 1 merges into the table created by batch 0)
        mock_merge.return_value.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = {}

        mock_chunk_size.return_value = 1
        await _run(
            team=team,
            schema_name="test_table",
            table_name="postgres_test_table",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    if pipeline_mode == "non_dlt":
        mock_post_run_operations.assert_called_once()

        mock_merge.assert_not_called()
        assert mock_write.call_count == 2

        _, first_call_kwargs = mock_write.call_args_list[0]
        _, second_call_kwargs = mock_write.call_args_list[1]

        assert first_call_kwargs == {
            "mode": "overwrite",
            "schema_mode": "overwrite",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }

        assert second_call_kwargs == {
            "mode": "append",
            "schema_mode": "merge",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }
    else:
        mock_v3_post_load.assert_called_once()
        mock_merge.assert_not_called()
        assert mock_write.call_count == 2

        _, first_call_kwargs = mock_write.call_args_list[0]
        _, second_call_kwargs = mock_write.call_args_list[1]

        assert first_call_kwargs == {
            "mode": "overwrite",
            "schema_mode": "overwrite",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }

        assert second_call_kwargs == {
            "mode": "append",
            "schema_mode": "merge",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync_uncapped_chunk_size(
    team, postgres_config, postgres_connection, pipeline_mode
):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1
        ),
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.run_post_load_operations",
            new_callable=AsyncMock,
        ),
    ):
        await _run(
            team=team,
            schema_name="test_table",
            table_name="postgres_test_table",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    # With uncapped chunk size, all rows fit in 1 batch. Both modes: 1 write (overwrite), no merge.
    if pipeline_mode == "non_dlt":
        mock_post_run_operations.assert_called_once()

    mock_merge.assert_not_called()
    assert mock_write.call_count == 1

    _, first_call_kwargs = mock_write.call_args_list[0]

    assert first_call_kwargs == {
        "mode": "overwrite",
        "schema_mode": "overwrite",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "commit_properties": mock.ANY,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync_after_reset(team, postgres_config, postgres_connection, pipeline_mode):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_table (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    _, inputs = await _run(
        team=team,
        schema_name="test_table",
        table_name="postgres_test_table",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
        ignore_assertions=True,
    )

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._get_table_chunk_size"
        ) as mock_chunk_size,
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.run_post_load_operations",
            new_callable=AsyncMock,
        ) as mock_v3_post_load,
    ):
        mock_merge.return_value.when_matched_update_all.return_value.when_not_matched_insert_all.return_value.execute.return_value = {}

        mock_chunk_size.return_value = 1
        await _execute_run(
            str(uuid.uuid4()),
            ExternalDataWorkflowInputs(
                team_id=inputs.team_id,
                external_data_source_id=inputs.external_data_source_id,
                external_data_schema_id=inputs.external_data_schema_id,
                reset_pipeline=True,
            ),
            [],
        )
        await _replay_v3_consumer(team_id=inputs.team_id, schema_id=inputs.external_data_schema_id)

    if pipeline_mode == "non_dlt":
        mock_post_run_operations.assert_called_once()

        mock_merge.assert_not_called()
        assert mock_write.call_count == 2

        _, first_call_kwargs = mock_write.call_args_list[0]
        _, second_call_kwargs = mock_write.call_args_list[1]

        assert first_call_kwargs == {
            "mode": "overwrite",
            "schema_mode": "overwrite",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }

        assert second_call_kwargs == {
            "mode": "append",
            "schema_mode": "merge",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }
    else:
        mock_v3_post_load.assert_called_once()
        mock_merge.assert_not_called()
        assert mock_write.call_count == 2

        _, first_call_kwargs = mock_write.call_args_list[0]
        _, second_call_kwargs = mock_write.call_args_list[1]

        assert first_call_kwargs == {
            "mode": "overwrite",
            "schema_mode": "overwrite",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }

        assert second_call_kwargs == {
            "mode": "append",
            "schema_mode": "merge",
            "table_or_uri": mock.ANY,
            "data": mock.ANY,
            "partition_by": mock.ANY,
            "commit_properties": mock.ANY,
        }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_with_int_id(team, postgres_config, postgres_connection, minio_client):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_partition_folders (id integer, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (1, '2025-01-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (2, '2025-02-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    workflow_id, inputs = await _run(
        team=team,
        schema_name="test_partition_folders",
        table_name="postgres_test_partition_folders",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
        ignore_assertions=True,
    )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    latest_job = jobs[0]
    folder_path = await sync_to_async(latest_job.folder_path)()

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    # Using numerical primary key causes partitions not be md5'd
    assert any(f"{PARTITION_KEY}=0" in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["id"]
    assert schema.partition_mode == "numerical"
    assert schema.partition_count is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_with_uuid_id_and_created_at(team, postgres_config, postgres_connection, minio_client):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_partition_folders (id uuid, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES ('{uuid}', '2025-01-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"], uuid=str(uuid.uuid4())
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES ('{uuid}', '2025-02-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"], uuid=str(uuid.uuid4())
        )
    )
    await postgres_connection.commit()

    workflow_id, inputs = await _run(
        team=team,
        schema_name="test_partition_folders",
        table_name="postgres_test_partition_folders",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "timestamp"},
        ignore_assertions=True,
    )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    latest_job = jobs[0]
    folder_path = await sync_to_async(latest_job.folder_path)()

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    # Using datetime partition mode with created_at and week format (the default)
    assert any(f"{PARTITION_KEY}=2025-w01" in obj["Key"] for obj in s3_objects["Contents"])
    assert any(f"{PARTITION_KEY}=2025-w05" in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["created_at"]
    assert schema.partition_mode == "datetime"
    assert schema.partition_format == "week"
    assert schema.partition_count is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_in_place_repartition_to_finer_datetime_format(team, postgres_config, postgres_connection, minio_client):
    # A datetime-partitioned table that has outgrown its scheme is repartitioned in place to a finer
    # (daily) layout from the data already in S3 — no source re-pull — and the next incremental merge
    # then runs against the new layout. Runs the whole pipeline (V2 + V3 via the pipeline_mode fixture).
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_repartition (id uuid PRIMARY KEY, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )
    for ts in ("2025-01-15", "2025-01-20", "2025-02-10", "2025-02-15"):
        await postgres_connection.execute(
            "INSERT INTO {schema}.test_repartition (id, created_at) VALUES ('{id}', '{ts}T12:00:00.000Z')".format(
                schema=postgres_config["schema"], id=uuid.uuid4(), ts=ts
            )
        )
    await postgres_connection.commit()

    job_inputs = {
        "host": postgres_config["host"],
        "port": postgres_config["port"],
        "database": postgres_config["database"],
        "user": postgres_config["user"],
        "password": postgres_config["password"],
        "schema": postgres_config["schema"],
        "ssh_tunnel_enabled": "False",
    }

    # First sync → datetime partitioning on created_at (week format is the default).
    _workflow_id, inputs = await _run(
        team=team,
        schema_name="test_repartition",
        table_name="postgres_test_repartition",
        source_type="Postgres",
        job_inputs=job_inputs,
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "timestamp"},
        ignore_assertions=True,
    )

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partition_mode == "datetime"
    assert schema.partition_format == "week"

    count_before = await sync_to_async(execute_hogql_query)("SELECT count() FROM postgres_test_repartition", team)
    assert count_before.results[0][0] == 4

    # Queue an in-place repartition to a finer (daily) format, then add a new row and re-sync. The
    # pre-extraction activity rewrites the four existing rows to daily partitions; the incremental
    # merge then folds in the new March row on that new layout.
    await sync_to_async(schema.set_repartition_pending)(
        {
            "partition_mode": "datetime",
            "partition_format": "day",
            "partition_keys": ["created_at"],
            "partition_count": None,
            "partition_size": None,
            "trigger_reason": "test",
            "attempts": 0,
        }
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_repartition (id, created_at) VALUES ('{id}', '2025-03-05T12:00:00.000Z')".format(
            schema=postgres_config["schema"], id=uuid.uuid4()
        )
    )
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partition_format == "day", "repartition should have switched the table to daily partitions"
    assert schema.repartition_pending is None, "the activity should have consumed the pending repartition"

    job = await sync_to_async(
        lambda: (
            ExternalDataJob.objects.filter(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
            .order_by("-created_at")
            .first()
        )
    )()
    assert job is not None
    folder_path = await sync_to_async(job.folder_path)()
    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_repartition/")
    keys = [obj["Key"] for obj in s3_objects["Contents"]]
    # Live data is now in daily partition folders (%Y-%m-%d); the old weekly (%G-wWW) folders are gone.
    assert any(f"{PARTITION_KEY}=2025-01-15" in k for k in keys), keys
    assert not any(f"{PARTITION_KEY}=2025-w" in k for k in keys), keys

    # No rows lost or duplicated by the rewrite + the subsequent merge.
    count_after = await sync_to_async(execute_hogql_query)("SELECT count() FROM postgres_test_repartition", team)
    assert count_after.results[0][0] == 5


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "partition_format,test_dates,expected_partitions",
    [
        ("day", ["2025-01-01", "2025-01-02", "2025-01-03"], ["2025-01-01", "2025-01-02", "2025-01-03"]),
        ("week", ["2024-12-31", "2025-01-01", "2025-01-06"], ["2025-w01", "2025-w01", "2025-w02"]),
        ("month", ["2025-01-01", "2025-02-01", "2025-03-01"], ["2025-01", "2025-02", "2025-03"]),
    ],
)
async def test_partition_folders_with_uuid_id_and_created_at_with_parametrized_format(
    team, postgres_config, postgres_connection, minio_client, partition_format, test_dates, expected_partitions
):
    table_name = f"test_partition_{partition_format}"

    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.{table_name} (id uuid, created_at timestamp)".format(
            schema=postgres_config["schema"], table_name=table_name
        )
    )

    for date in test_dates:
        await postgres_connection.execute(
            "INSERT INTO {schema}.{table_name} (id, created_at) VALUES ('{uuid}', '{date}T12:00:00.000Z')".format(
                schema=postgres_config["schema"], table_name=table_name, uuid=str(uuid.uuid4()), date=date
            )
        )

    await postgres_connection.commit()

    workflow_id, inputs = await _run(
        team=team,
        schema_name=table_name,
        table_name=f"postgres_{table_name}",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "timestamp"},
        ignore_assertions=True,
    )

    # Set the parition format on the schema - this will persist after a reset_pipeline
    schema: ExternalDataSchema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)
    schema.sync_type_config["partition_format"] = partition_format
    await sync_to_async(schema.save)()

    # Resync with reset_pipeline = True
    await _execute_run(
        str(uuid.uuid4()),
        ExternalDataWorkflowInputs(
            team_id=inputs.team_id,
            external_data_source_id=inputs.external_data_source_id,
            external_data_schema_id=inputs.external_data_schema_id,
            reset_pipeline=True,
        ),
        [],
    )
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    latest_job = jobs[0]
    folder_path = await sync_to_async(latest_job.folder_path)()

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/{table_name}/")

    # using datetime partition mode with created_at - formatted to day, week, or month
    for expected_partition in expected_partitions:
        assert any(f"{PARTITION_KEY}={expected_partition}" in obj["Key"] for obj in s3_objects["Contents"]), (
            f"Expected partition {expected_partition} not found in S3 objects"
        )

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["created_at"]
    assert schema.partition_mode == "datetime"
    assert schema.partition_format == partition_format
    assert schema.partition_count is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_with_existing_table(team, postgres_config, postgres_connection, minio_client):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_partition_folders (id integer, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (1, '2025-01-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (2, '2025-02-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    async def mock_setup_partitioning(pa_table, existing_delta_table, schema, resource, logger):
        return pa_table

    def mock_apply_partitioning(export_signal, pa_table, existing_delta_table, schema):
        return pa_table

    # Emulate an existing table with no partitions
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline.setup_partitioning",
            mock_setup_partitioning,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor._apply_partitioning",
            mock_apply_partitioning,
        ),
    ):
        workflow_id, inputs = await _run(
            team=team,
            schema_name="test_partition_folders",
            table_name="postgres_test_partition_folders",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    latest_job = jobs[0]
    folder_path = await sync_to_async(latest_job.folder_path)()

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    # Confirm there are no partitions in S3
    assert not any(PARTITION_KEY in obj["Key"] for obj in s3_objects["Contents"])

    # Add new data to the postgres table
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (3, '2025-03-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    # Resync
    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Reconfirm there are no partitions
    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")
    assert not any(PARTITION_KEY in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is False
    assert schema.partitioning_keys is None
    assert schema.partition_count is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_with_existing_table_and_pipeline_reset(
    team, postgres_config, postgres_connection, minio_client
):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_partition_folders (id integer, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (1, '2025-01-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (2, '2025-02-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    async def mock_setup_partitioning(pa_table, existing_delta_table, schema, resource, logger):
        return pa_table

    def mock_apply_partitioning(export_signal, pa_table, existing_delta_table, schema):
        return pa_table

    # Emulate an existing table with no partitions
    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline.setup_partitioning",
            mock_setup_partitioning,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor._apply_partitioning",
            mock_apply_partitioning,
        ),
    ):
        workflow_id, inputs = await _run(
            team=team,
            schema_name="test_partition_folders",
            table_name="postgres_test_partition_folders",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    latest_job = jobs[0]
    folder_path = await sync_to_async(latest_job.folder_path)()

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    # Confirm there are no partitions in S3
    assert not any(PARTITION_KEY in obj["Key"] for obj in s3_objects["Contents"])

    # Update the schema to be incremental based on the created_at field
    schema: ExternalDataSchema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)
    schema.sync_type_config = {
        "incremental_field": "created_at",
        "incremental_field_type": "timestamp",
        "incremental_field_last_value": "2025-02-01T12:00:00.000Z",
    }
    await sync_to_async(schema.save)()

    # Resync with reset_pipeline = True
    await _execute_run(
        str(uuid.uuid4()),
        ExternalDataWorkflowInputs(
            team_id=inputs.team_id,
            external_data_source_id=inputs.external_data_source_id,
            external_data_schema_id=inputs.external_data_schema_id,
            reset_pipeline=True,
        ),
        [],
    )
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Confirm the table now has partitions
    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    assert any(f"{PARTITION_KEY}=" in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["id"]
    assert schema.partition_count is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_delta_merge_called_with_partition_predicate(
    team, postgres_config, postgres_connection, pipeline_mode
):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.test_partition_folders (id integer, created_at timestamp)".format(
            schema=postgres_config["schema"]
        )
    )

    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (1, '2025-01-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (2, '2025-02-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    # Emulate an existing table with no partitions
    workflow_id, inputs = await _run(
        team=team,
        schema_name="test_partition_folders",
        table_name="postgres_test_partition_folders",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "created_at", "incremental_field_type": "timestamp"},
        ignore_assertions=True,
    )

    # Insert a new row with created_at greater than the last synced value so the `>` operator picks it up
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES (3, '2025-03-01T12:00:00.000Z')".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.commit()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1
        ),
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.run_post_load_operations",
            new_callable=AsyncMock,
        ) as mock_v3_post_load,
    ):
        # Mocking the return of the delta merge as it gets JSON'ified
        mock_merge_instance = mock_merge.return_value
        mock_when_matched = mock_merge_instance.when_matched_update_all.return_value
        mock_when_not_matched = mock_when_matched.when_not_matched_insert_all.return_value
        mock_when_not_matched.execute.return_value = {}

        await _execute_run(
            str(uuid.uuid4()),
            inputs,
            [],
        )
        await _replay_v3_consumer(team_id=inputs.team_id, schema_id=inputs.external_data_schema_id)

    if pipeline_mode == "non_dlt":
        mock_post_run_operations.assert_called_once()
    else:
        mock_v3_post_load.assert_called_once()

    mock_write.assert_not_called()
    assert mock_merge.call_count == 1

    merge_call_args, first_call_kwargs = mock_merge.call_args_list[0]

    assert first_call_kwargs == {
        "source": mock.ANY,
        "source_alias": "source",
        "target_alias": "target",
        "predicate": f"source.id = target.id AND source.{PARTITION_KEY} = target.{PARTITION_KEY} AND target.{PARTITION_KEY} = '0'",
        "streamed_exec": True,
        "commit_properties": mock.ANY,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_row_tracking_incrementing(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.row_tracking (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.row_tracking (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract.decrement_rows"
        ) as mock_decrement_rows,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.finish_row_tracking"
        ) as mock_finish_row_tracking_workflow,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.finish_row_tracking"
        ) as mock_finish_row_tracking_consumer,
    ):
        _, inputs = await _run(
            team=team,
            schema_name="row_tracking",
            table_name="postgres_row_tracking",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
        )

    schema_id = inputs.external_data_schema_id

    mock_decrement_rows.assert_called_once_with(team.id, schema_id, 1)
    if _current_pipeline_mode == "v3":
        mock_finish_row_tracking_consumer.assert_called_once()
    else:
        mock_finish_row_tracking_workflow.assert_called_once()

    assert schema_id is not None
    with override_settings(
        DATA_WAREHOUSE_REDIS_HOST="localhost",
        DATA_WAREHOUSE_REDIS_PORT="6379",
    ):
        row_count_in_redis = await get_rows(team.id, schema_id)

    assert row_count_in_redis == 1

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_row_tracking", team)
    columns = res.columns

    assert columns is not None
    assert len(columns) == 1
    assert any(x == "id" for x in columns)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_duplicate_primary_key(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.duplicate_primary_key (id integer)".format(
            schema=postgres_config["schema"]
        )
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.duplicate_primary_key (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.duplicate_primary_key (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.duplicate_primary_key (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        pytest.raises(Exception),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.update_should_sync"
        ) as mock_update_should_sync,
    ):
        await _run(
            team=team,
            schema_name="duplicate_primary_key",
            table_name="postgres_duplicate_primary_key",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
        )

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(
        team_id=team.id, schema__name="duplicate_primary_key"
    )

    assert job.status == ExternalDataJob.Status.FAILED
    assert job.latest_error is not None
    assert (
        "The primary keys for this table are not unique. We can't sync incrementally until the table has a unique primary key"
        in job.latest_error
    )

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_duplicate_primary_key", team)

    schema: ExternalDataSchema = await sync_to_async(ExternalDataSchema.objects.get)(id=job.schema_id)
    mock_update_should_sync.assert_called_once_with(
        schema_id=str(schema.id),
        team_id=team.id,
        should_sync=False,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_earliest_incremental_value(team, stripe_balance_transaction, mock_stripe_client):
    _, inputs = await _run(
        team=team,
        schema_name=STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_balance_transaction["data"],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.incremental_field_earliest_value == stripe_balance_transaction["data"][0]["created"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_append_only_table(team, mock_stripe_client):
    _, inputs = await _run(
        team=team,
        schema_name=STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.APPEND,
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )

    with mock.patch.object(DeltaTableHelper, "compact_table"):
        await _execute_run(str(uuid.uuid4()), inputs, [])

    run_for_replay = await sync_to_async(
        ExternalDataJob.objects.filter(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
        .order_by("-created_at")
        .first
    )()
    await _replay_v3_consumer(
        team_id=team.pk,
        schema_id=inputs.external_data_schema_id,
        job_id=str(run_for_replay.id) if run_for_replay else None,
    )

    res = await sync_to_async(execute_hogql_query)("SELECT id FROM stripe_balancetransaction", team)

    # We should now have 2 rows with the same `id`
    assert len(res.results) == 2
    assert res.results[0][0] == res.results[1][0]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_worker_shutdown_desc_sort_order(team):
    """Testing that a descending sort ordered source will not trigger the rescheduling"""

    def mock_raise_if_is_worker_shutdown(self):
        raise WorkerShuttingDownError("test_id", "test_type", "test_queue", 1, "test_workflow", "test_workflow_type")

    def mock_get_messages(*args, **kwargs):
        yield {
            "id": "test-message-id",
            "conversation_updated_at": datetime.now().isoformat(),
            "created_at": datetime.now().isoformat(),
        }

    with (
        mock.patch.object(ShutdownMonitor, "raise_if_is_worker_shutdown", mock_raise_if_is_worker_shutdown),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
        ) as mock_trigger_schedule_buffer_one,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vitally.vitally.get_messages",
            mock_get_messages,
        ),
    ):
        _, inputs = await _run(
            team=team,
            schema_name="Messages",
            table_name="vitally_messages",
            source_type="Vitally",
            job_inputs={
                "secret_token": "test_token",
                "region": {"selection": "EU", "subdomain": ""},
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "conversation_updated_at", "incremental_field_type": "datetime"},
            ignore_assertions=True,
        )

    # assert that the running job was completed successfully and that the new workflow was NOT triggered
    mock_trigger_schedule_buffer_one.assert_not_called()

    run: ExternalDataJob | None = await get_latest_run_if_exists(
        team_id=inputs.team_id, pipeline_id=inputs.external_data_source_id
    )

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_worker_shutdown_triggers_schedule_buffer_one(team, zendesk_brands):
    def mock_raise_if_is_worker_shutdown(self):
        raise WorkerShuttingDownError("test_id", "test_type", "test_queue", 1, "test_workflow", "test_workflow_type")

    with (
        mock.patch.object(ShutdownMonitor, "raise_if_is_worker_shutdown", mock_raise_if_is_worker_shutdown),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
        ) as mock_trigger_schedule_buffer_one,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1
        ),
    ):
        _, inputs = await _run(
            team=team,
            schema_name="brands",
            table_name="zendesk_brands",
            source_type="Zendesk",
            job_inputs={
                "subdomain": "test",
                "api_key": "test_api_key",
                "email_address": "test@posthog.com",
            },
            mock_data_response=zendesk_brands["brands"],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "created_at", "incremental_field_type": "datetime"},
            ignore_assertions=True,
        )

    # assert that the running job was completed successfully and that the new workflow was triggered
    mock_trigger_schedule_buffer_one.assert_called_once_with(mock.ANY, str(inputs.external_data_schema_id))

    run: ExternalDataJob | None = await get_latest_run_if_exists(
        team_id=inputs.team_id, pipeline_id=inputs.external_data_source_id
    )

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_billing_limits_too_many_rows(team, postgres_config, postgres_connection):
    from ee.api.test.test_billing import create_billing_customer
    from ee.models.license import License

    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.billing_limits (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.billing_limits (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.billing_limits (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        mock.patch("ee.api.billing.requests.get") as mock_billing_request,
        mock.patch("posthog.cloud_utils.is_instance_licensed_cached", None),
    ):
        await sync_to_async(License.objects.create)(
            key="12345::67890",
            plan="enterprise",
            valid_until=datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
        )

        mock_res = create_billing_customer()
        usage_summary = mock_res.get("usage_summary") or {}
        mock_billing_request.return_value.status_code = 200
        mock_billing_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            },
            "customer": {
                **mock_res,
                "usage_summary": {**usage_summary, "rows_synced": {"limit": 0, "usage": 0}},
            },
        }

        await _run(
            team=team,
            schema_name="billing_limits",
            table_name="postgres_billing_limits",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(
        team_id=team.id, schema__name="billing_limits"
    )

    assert job.status == ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_billing_limits", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_billing_limits_too_many_rows_previously(team, postgres_config, postgres_connection):
    from ee.api.test.test_billing import create_billing_customer
    from ee.models.license import License

    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.billing_limits (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.billing_limits (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.billing_limits (id) VALUES (2)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    with (
        mock.patch("ee.api.billing.requests.get") as mock_billing_request,
        mock.patch("posthog.cloud_utils.is_instance_licensed_cached", None),
    ):
        with freeze_time("2023-01-01"):
            source = await sync_to_async(ExternalDataSource.objects.create)(team=team)

        # A previous job that reached the billing limit
        await sync_to_async(ExternalDataJob.objects.create)(
            team=team,
            rows_synced=10,
            pipeline=source,
            finished_at=datetime.now(),
            billable=True,
            status=ExternalDataJob.Status.COMPLETED,
        )

        await sync_to_async(License.objects.create)(
            key="12345::67890",
            plan="enterprise",
            valid_until=datetime(2038, 1, 19, 3, 14, 7, tzinfo=ZoneInfo("UTC")),
        )

        mock_res = create_billing_customer()
        usage_summary = mock_res.get("usage_summary") or {}
        mock_billing_request.return_value.status_code = 200
        mock_billing_request.return_value.json.return_value = {
            "license": {
                "type": "scale",
            },
            "customer": {
                **mock_res,
                "usage_summary": {**usage_summary, "rows_synced": {"limit": 10, "usage": 0}},
            },
        }

        await _run(
            team=team,
            schema_name="billing_limits",
            table_name="postgres_billing_limits",
            source_type="Postgres",
            job_inputs={
                "host": postgres_config["host"],
                "port": postgres_config["port"],
                "database": postgres_config["database"],
                "user": postgres_config["user"],
                "password": postgres_config["password"],
                "schema": postgres_config["schema"],
                "ssh_tunnel_enabled": "False",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
            ignore_assertions=True,
        )

    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(
        team_id=team.id, schema__name="billing_limits"
    )

    assert job.status == ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)(f"SELECT * FROM postgres_billing_limits", team)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_pipeline_mb_chunk_size(team, zendesk_brands, pipeline_mode):
    if pipeline_mode == "v3":
        process_mock = mock.patch.object(PipelineV3, "_process_batch", new_callable=AsyncMock)
    else:
        process_mock = mock.patch.object(PipelineNonDLT, "_process_pa_table")

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE_BYTES",
            1,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE",
            5000,
        ),  # Explicitly make this big
        process_mock as mock_process,
    ):
        await _run(
            team=team,
            schema_name="brands",
            table_name="zendesk_brands",
            source_type="Zendesk",
            job_inputs={
                "subdomain": "test",
                "api_key": "test_api_key",
                "email_address": "test@posthog.com",
            },
            mock_data_response=[*zendesk_brands["brands"], *zendesk_brands["brands"]],  # Return two items
            ignore_assertions=True,
        )

    # Returning two items should cause the pipeline to process each item individually
    assert mock_process.call_count == 2


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_deleting_schemas(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.table_1 (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.table_1 (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.table_2 (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    _, inputs = await _run(
        team=team,
        schema_name="table_1",
        table_name="postgres_table_1",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
    )

    @sync_to_async
    def get_schemas():
        schemas = ExternalDataSchema.objects.filter(source_id=inputs.external_data_source_id, deleted=False)

        return list(schemas)

    # Schema discovery now runs on its own per-source schedule — simulate a tick
    # of that schedule to discover the second table.
    await sync_to_async(sync_new_schemas_activity)(
        SyncNewSchemasActivityInputs(source_id=str(inputs.external_data_source_id), team_id=inputs.team_id)
    )

    schemas = await get_schemas()
    assert len(schemas) == 2

    # Drop the table we've not synced yet
    await postgres_connection.execute("DROP TABLE {schema}.table_2".format(schema=postgres_config["schema"]))
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])

    # Simulate the next tick of the per-source discovery schedule.
    await sync_to_async(sync_new_schemas_activity)(
        SyncNewSchemasActivityInputs(source_id=str(inputs.external_data_source_id), team_id=inputs.team_id)
    )

    schemas = await get_schemas()

    # It should have soft deleted the unsynced table
    assert len(schemas) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_deleting_schemas_with_pre_synced_data(team, postgres_config, postgres_connection):
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.table_1 (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.table_1 (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.table_2 (id integer)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.table_2 (id) VALUES (1)".format(schema=postgres_config["schema"])
    )
    await postgres_connection.commit()

    # Sync both tables
    _, inputs = await _run(
        team=team,
        schema_name="table_1",
        table_name="postgres_table_1",
        source_type="Postgres",
        job_inputs={
            "host": postgres_config["host"],
            "port": postgres_config["port"],
            "database": postgres_config["database"],
            "user": postgres_config["user"],
            "password": postgres_config["password"],
            "schema": postgres_config["schema"],
            "ssh_tunnel_enabled": "False",
        },
        mock_data_response=[],
    )

    @sync_to_async
    def get_schemas():
        schemas = ExternalDataSchema.objects.filter(source_id=inputs.external_data_source_id, deleted=False)

        return list(schemas)

    # Schema discovery now runs on its own per-source schedule — simulate a tick.
    await sync_to_async(sync_new_schemas_activity)(
        SyncNewSchemasActivityInputs(source_id=str(inputs.external_data_source_id), team_id=inputs.team_id)
    )

    schemas = await get_schemas()
    assert len(schemas) == 2

    # Drop the table that we've already synced
    await postgres_connection.execute("DROP TABLE {schema}.table_1".format(schema=postgres_config["schema"]))
    await postgres_connection.commit()

    unsynced_schema_ids = [s.id for s in schemas if s.id != inputs.external_data_schema_id]
    assert len(unsynced_schema_ids) == 1
    unsynced_schema_id = unsynced_schema_ids[0]
    await _execute_run(
        str(uuid.uuid4()),
        ExternalDataWorkflowInputs(
            team_id=inputs.team_id,
            external_data_source_id=inputs.external_data_source_id,
            external_data_schema_id=unsynced_schema_id,  # the schema id of the second table
            billable=inputs.billable,
        ),
        [],
    )

    # Simulate the next tick of the per-source discovery schedule.
    await sync_to_async(sync_new_schemas_activity)(
        SyncNewSchemasActivityInputs(source_id=str(inputs.external_data_source_id), team_id=inputs.team_id)
    )

    schemas = await get_schemas()
    # Because table_1 has already been synced and we hold data for it, we dont delete the schema
    assert len(schemas) == 2

    # The schema with the deleted upstream table should now have "should_sync" updated to False and status set to completed
    synced_schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert synced_schema.should_sync is False
    assert synced_schema.status == ExternalDataSchema.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_timestamped_query_folder(team, stripe_balance_transaction, mock_stripe_client, minio_client):
    datetime_1 = datetime.now()
    with freeze_time(datetime_1):
        workflow_id, inputs = await _run(
            team=team,
            schema_name=STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
            table_name="stripe_balancetransaction",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_balance_transaction["data"],
        )

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    folder_path = await sync_to_async(schema.folder_path)()

    # Sync a second time 5 minutes later
    datetime_2 = datetime_1 + timedelta(minutes=5)
    with freeze_time(datetime_2):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])
        await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Check the query folders now - both sync folders should exist
    s3_objects_datetime_1 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_1.timestamp())}/"
    )

    s3_objects_datetime_2 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_2.timestamp())}/"
    )

    assert len(s3_objects_datetime_1["Contents"]) != 0
    assert len(s3_objects_datetime_2["Contents"]) != 0

    # Sync a third time 3 minutes later (still under 10 mins since the first sync)
    datetime_3 = datetime_2 + timedelta(minutes=3)
    with freeze_time(datetime_3):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])
        await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Check the query folders now - all 3 sync folders should exist
    s3_objects_datetime_1 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_1.timestamp())}/"
    )

    s3_objects_datetime_2 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_2.timestamp())}/"
    )

    s3_objects_datetime_3 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_3.timestamp())}/"
    )

    assert len(s3_objects_datetime_1["Contents"]) != 0
    assert len(s3_objects_datetime_2["Contents"]) != 0
    assert len(s3_objects_datetime_3["Contents"]) != 0

    # Sync a fourth time 5 minutes later (now over 10 mins since the first sync)
    datetime_4 = datetime_3 + timedelta(minutes=5)
    with freeze_time(datetime_4):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])
        await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Check the query folders now - this should delete the first sync folder but keep three others
    s3_objects_datetime_1 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_1.timestamp())}/"
    )

    s3_objects_datetime_2 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_2.timestamp())}/"
    )

    s3_objects_datetime_3 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_3.timestamp())}/"
    )

    s3_objects_datetime_4 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_4.timestamp())}/"
    )

    assert len(s3_objects_datetime_1.get("Contents", [])) == 0  # first folder should be deleted
    assert len(s3_objects_datetime_2["Contents"]) != 0
    assert len(s3_objects_datetime_3["Contents"]) != 0
    assert len(s3_objects_datetime_4["Contents"]) != 0

    # Sync a fifth time 1 min later but with a reduced query file delete buffer
    datetime_5 = datetime_4 + timedelta(minutes=1)
    with (
        freeze_time(datetime_5),
        mock.patch("products.warehouse_sources.backend.temporal.data_imports.util.S3_DELETE_TIME_BUFFER", 1),
    ):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])
        await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Check the query folders now - this should delete all folders except the latest two
    s3_objects_datetime_1 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_1.timestamp())}/"
    )

    s3_objects_datetime_2 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_2.timestamp())}/"
    )

    s3_objects_datetime_3 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_3.timestamp())}/"
    )

    s3_objects_datetime_4 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_4.timestamp())}/"
    )

    s3_objects_datetime_5 = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query_{int(datetime_5.timestamp())}/"
    )

    assert len(s3_objects_datetime_1.get("Contents", [])) == 0
    assert len(s3_objects_datetime_2.get("Contents", [])) == 0
    assert len(s3_objects_datetime_3.get("Contents", [])) == 0
    assert (
        len(s3_objects_datetime_4["Contents"]) != 0  # we keep the most recent two folders if they're older than 10 mins
    )
    assert len(s3_objects_datetime_5["Contents"]) != 0  # this is the latest live queryable folder

    # Make sure the old format query folder doesn't exist
    s3_objects_old_format = await minio_client.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query/"
    )
    assert len(s3_objects_old_format.get("Contents", [])) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_resumable_source_shutdown(team, stripe_customer, mock_stripe_client):
    with mock.patch.object(ShutdownMonitor, "raise_if_is_worker_shutdown") as mock_raise_if_is_worker_shutdown:
        await _run(
            team=team,
            schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
            table_name="stripe_customer",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_customer["data"],
            ignore_assertions=True,
        )

        mock_raise_if_is_worker_shutdown.assert_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_delta_commit_metadata_and_idempotency_fallback(team, stripe_customer, mock_stripe_client):
    """V3 only: every delta commit on the writer side is tagged with (run_uuid, batch_index)
    in userMetadata, and `is_batch_already_processed` can fall back to delta history when
    the Redis idempotency flag is missing.

    This exercises the writer-side idempotency gap: if the writer crashes between
    `write_to_deltalake` committing and `mark_batch_as_processed` running, Kafka redelivery
    would otherwise re-write the same batch and produce duplicate rows. The delta-history
    fallback closes that gap.
    """
    if _current_pipeline_mode != "v3":
        pytest.skip("only applies to pipeline_v3")

    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.idempotency import (
        is_batch_already_processed,
    )

    _, inputs = await _run(
        team=team,
        schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
        table_name="stripe_customer",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_customer["data"],
    )

    job: ExternalDataJob | None = await sync_to_async(
        lambda: (
            ExternalDataJob.objects.filter(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
            .order_by("-created_at")
            .first()
        )
    )()
    assert job is not None

    # The v3 writer runs under these overridden settings (see `_replay_v3_consumer`),
    # so reading the delta table back must use the same storage config.
    with override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        BUCKET_PATH=BUCKET_NAME,
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        DATA_WAREHOUSE_REDIS_HOST="localhost",
        DATA_WAREHOUSE_REDIS_PORT="6379",
        DATAWAREHOUSE_BUCKET=BUCKET_NAME,
    ):
        delta_table_helper = DeltaTableHelper(
            resource_name=STRIPE_CUSTOMER_RESOURCE_NAME,
            job=job,
            logger=mock.MagicMock(adebug=AsyncMock(), ainfo=AsyncMock()),
        )

        # 1. Every commit written by the v3 writer should carry userMetadata with (run_uuid, batch_index).
        delta_table = await delta_table_helper.get_delta_table()
        assert delta_table is not None

        # delta-rs 1.x inlines `CommitProperties.custom_metadata` entries directly
        # into the commit dict alongside `operation`/`timestamp`/etc., so we match
        # by presence of our metadata keys rather than by `operation`. Operation can
        # be WRITE (full_refresh/append) or MERGE (incremental/cdc), depending on the
        # sync type — the keys are the only stable signal.
        history = await sync_to_async(delta_table.history)(limit=50)
        tagged_commits = [c for c in history if "run_uuid" in c and "batch_index" in c]
        assert len(tagged_commits) > 0, "expected at least one commit tagged with run_uuid + batch_index"

        observed_run_uuids: set[str] = set()
        observed_batch_indices: set[str] = set()
        for commit in tagged_commits:
            observed_run_uuids.add(commit["run_uuid"])
            observed_batch_indices.add(commit["batch_index"])

        # All commits should belong to the same run.
        assert len(observed_run_uuids) == 1
        run_uuid = next(iter(observed_run_uuids))

        # 2. Delta-history fallback returns True for a known committed batch.
        known_batch_index = int(next(iter(observed_batch_indices)))
        found = await sync_to_async(is_batch_already_processed)(
            team_id=team.pk,
            schema_id=str(inputs.external_data_schema_id),
            run_uuid=run_uuid,
            batch_index=known_batch_index,
            delta_table_helper=delta_table_helper,
        )
        assert found is True, "delta-history fallback should detect a committed batch"

        # 3. And False for a run_uuid that was never written — a different sync's batch.
        not_found = await sync_to_async(is_batch_already_processed)(
            team_id=team.pk,
            schema_id=str(inputs.external_data_schema_id),
            run_uuid="never-existed-run-uuid",
            batch_index=0,
            delta_table_helper=delta_table_helper,
        )
        assert not_found is False

    # 4. Final no-duplicates assertion: every customer row appears exactly once.
    res = await sync_to_async(execute_hogql_query)(
        "SELECT count() AS total, count(DISTINCT id) AS distinct_ids FROM stripe_customer", team
    )
    assert res.results is not None and len(res.results) == 1
    total, distinct_ids = res.results[0]
    assert total == distinct_ids, f"duplicate rows in destination table: total={total} distinct_ids={distinct_ids}"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("pipeline_mode", ["non_dlt"], indirect=True)
async def test_non_retryable_error_short_circuiting(team, stripe_customer, mock_stripe_client, pipeline_mode):
    # The retry/short-circuit behaviour lives in the workflow + activity layer, upstream of the
    # v3/non_dlt split, so running a single pipeline mode is enough — running both just doubles the
    # cost. Each attempt re-executes the whole import activity, so we also shrink the retry budgets
    # to keep the test fast: cap resumable retries at 3 and make the non-retryable path give up after
    # 2 attempts. The contrast (3 retryable attempts vs 2 non-retryable attempts) is what proves the
    # short-circuit; the prod caps (15 / 3) are just larger values of the same mechanism.
    resumable_retry_cap = 3
    non_retryable_attempts = 2

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.MAX_RESUMABLE_SOURCE_RETRIES",
            resumable_retry_cap,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract.NON_RETRYABLE_ERROR_RETRY_LIMIT",
            non_retryable_attempts - 1,
        ),
    ):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.get_rows"
        ) as mock_get_rows:
            mock_get_rows.side_effect = Exception("Some error that doesn't retry")

            with pytest.raises(Exception):
                await _run(
                    team=team,
                    schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
                    table_name="stripe_customer",
                    source_type="Stripe",
                    job_inputs={
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                        "stripe_account_id": "acct_id",
                    },
                    mock_data_response=stripe_customer["data"],
                    ignore_assertions=True,
                )

        # Resumable source syncs retry up to the configured cap
        assert mock_get_rows.call_count == resumable_retry_cap

        source_cls = SourceRegistry.get_source(ExternalDataSourceType.STRIPE)
        non_retryable_errors = source_cls.get_non_retryable_errors()
        non_retryable_error = next(iter(non_retryable_errors.keys()))

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe.get_rows"
        ) as mock_get_rows:
            mock_get_rows.side_effect = Exception(non_retryable_error)

            with pytest.raises(Exception):
                await _run(
                    team=team,
                    schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
                    table_name="stripe_customer",
                    source_type="Stripe",
                    job_inputs={
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                        "stripe_account_id": "acct_id",
                    },
                    mock_data_response=stripe_customer["data"],
                    ignore_assertions=True,
                )

        # Non-retryable errors short-circuit before reaching the resumable cap
        assert mock_get_rows.call_count == non_retryable_attempts
        assert non_retryable_attempts < resumable_retry_cap


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cdp_producer_push_to_s3(team, stripe_customer, mock_stripe_client, minio_client):
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "stripe.customer"}]},
    )

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.external_data_job.start_child_workflow"
    ) as mock_start_child_workflow:
        _, inputs = await _run(
            team=team,
            schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
            table_name="stripe_customer",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_customer["data"],
        )

    @sync_to_async
    def get_jobs():
        jobs = ExternalDataJob.objects.filter(
            team_id=team.pk,
            pipeline_id=inputs.external_data_source_id,
        ).order_by("-created_at")

        return list(jobs)

    jobs = await get_jobs()
    assert len(jobs) > 0
    job = jobs[0]

    path = f"cdp_producer/{team.id}/{inputs.external_data_schema_id}/{job.id}/"

    files = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=path)

    assert len(files["Contents"]) == 1
    file = files["Contents"][0]
    assert file["Key"] == f"{path}chunk_0.parquet"

    mock_start_child_workflow.assert_called_with(
        workflow="dwh-cdp-producer-job",
        arg=mock.ANY,
        id=f"dwh-cdp-producer-job-{job.id}",
        task_queue=mock.ANY,
        parent_close_policy=mock.ANY,
        retry_policy=mock.ANY,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_cdp_producer_push_to_kafka(team, stripe_customer, mock_stripe_client, minio_client, pipeline_mode):
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        filters={"source": "data-warehouse-table", "data_warehouse": [{"table_name": "stripe.customer"}]},
    )

    mock_kafka_producer = mock.MagicMock()
    mock_kafka_producer.produce = mock.AsyncMock()
    mock_kafka_producer.flush = mock.AsyncMock()
    mock_kafka_producer.close = mock.AsyncMock()

    # CDPProducer now uses `async_producer_scope(profile=CYCLOTRON)` from the routing
    # module instead of a per-instance `_get_kafka_producer` method; patch the async
    # context manager at its import site.
    @contextlib.asynccontextmanager
    async def _fake_scope(*args, **kwargs):
        yield mock_kafka_producer

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer.async_producer_scope",
            _fake_scope,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline.time.time_ns",
            return_value=1768828644858352000,
        ),
    ):
        _, inputs = await _run(
            team=team,
            schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
            table_name="stripe_customer",
            source_type="Stripe",
            job_inputs={
                "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
                "stripe_account_id": "acct_id",
            },
            mock_data_response=stripe_customer["data"],
        )

    mock_kafka_producer.produce.assert_called()
    call_kwargs = mock_kafka_producer.produce.call_args[1]

    expected_properties = {
        "delinquent": False,
        "object": "customer",
        "tax_exempt": "none",
        "address": None,
        "invoice_prefix": "0759376C",
        "balance": -1000,
        "currency": None,
        "livemode": False,
        "invoice_settings": '{"custom_fields":null,"default_payment_method":null,"footer":null,"rendering_options":null}',
        "metadata": "{}",
        "id": "cus_NffrFeUfNV2Hib",
        "next_invoice_sequence": 1,
        "email": "jennyrosen@example.com",
        "phone": None,
        "test_clock": None,
        "discount": None,
        "default_source": None,
        "created": 1680893993,
        "shipping": None,
        "name": "Jenny Rosen",
        "preferred_locales": "[]",
        "description": None,
        "_ph_debug": '{"load_id": 1768828644858352000}',
    }

    # non_dlt adds _ph_partition_key during extract; v3 applies partitioning in the consumer
    if pipeline_mode == "non_dlt":
        expected_properties["_ph_partition_key"] = "2023-w14"

    # The producer derives a deterministic event id per row per job. Its value depends on the
    # dynamic job id, so assert it is a valid UUID and compare the rest of the payload.
    data = call_kwargs["data"]
    assert str(uuid.UUID(data["event_id"])) == data["event_id"]
    assert {key: value for key, value in data.items() if key != "event_id"} == {
        "team_id": team.id,
        "table_name": "stripe.customer",
        "properties": expected_properties,
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_webhook_s3_charges(team, stripe_charge, mock_stripe_client, minio_client):
    # Initial sync to create delta table and mark initial_sync_complete
    _, inputs = await _run(
        team=team,
        schema_name=STRIPE_CHARGE_RESOURCE_NAME,
        table_name="stripe_charge",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_charge["data"],
        sync_type=ExternalDataSchema.SyncType.WEBHOOK,
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_charge", team)
    assert len(res.results) == 1

    # Create a webhook HogFunction linked to this schema via inputs
    schema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)
    schema_id_str = str(schema.id)
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        deleted=False,
        type="warehouse_source_webhook",
        inputs_schema=[{"key": "schema_mapping", "type": "json"}, {"key": "source_id", "type": "string"}],
        inputs={
            "schema_mapping": {"value": {"charge": schema_id_str}},
            "source_id": {"value": str(inputs.external_data_source_id)},
        },
    )

    assert schema.initial_sync_complete is True

    # Upload a webhook parquet file to MinIO in the expected location
    webhook_event = {
        "id": "evt_abc123",
        "type": "charge.refunded",
        "created": 1775760601,
        "data": {
            "object": {
                "id": "ch_abc123",
                "amount": 5000,
                "amount_refunded": 5000,
                "refunded": True,
                "object": "charge",
                "amount_captured": 1099,
                "application": None,
                "application_fee": None,
                "application_fee_amount": None,
                "balance_transaction": "txn_3MmlLrLkdIwHu7ix0uke3Ezy",
                "billing_details": {
                    "address": {
                        "city": None,
                        "country": None,
                        "line1": None,
                        "line2": None,
                        "postal_code": None,
                        "state": None,
                    },
                    "email": None,
                    "name": None,
                    "phone": None,
                },
                "calculated_statement_descriptor": "Stripe",
                "captured": True,
                "created": 1679090539,
                "currency": "usd",
                "customer": None,
                "description": None,
                "disputed": False,
                "failure_balance_transaction": None,
                "failure_code": None,
                "failure_message": None,
                "fraud_details": {},
                "invoice": None,
                "livemode": False,
                "metadata": {},
                "on_behalf_of": None,
                "outcome": {
                    "network_status": "approved_by_network",
                    "reason": None,
                    "risk_level": "normal",
                    "risk_score": 32,
                    "seller_message": "Payment complete.",
                    "type": "authorized",
                },
                "paid": True,
                "payment_intent": None,
                "payment_method": "card_1MmlLrLkdIwHu7ixIJwEWSNR",
                "payment_method_details": {
                    "card": {
                        "brand": "visa",
                        "checks": {"address_line1_check": None, "address_postal_code_check": None, "cvc_check": None},
                        "country": "US",
                        "exp_month": 3,
                        "exp_year": 2024,
                        "fingerprint": "mToisGZ01V71BCos",
                        "funding": "credit",
                        "installments": None,
                        "last4": "4242",
                        "mandate": None,
                        "network": "visa",
                        "three_d_secure": None,
                        "wallet": None,
                    },
                    "type": "card",
                },
                "receipt_email": None,
                "receipt_number": None,
                "receipt_url": "https://pay.stripe.com/receipts/payment/CAcaFwoVYWNjdF8xTTJKVGtMa2RJd0h1N2l4KOvG06AGMgZfBXyr1aw6LBa9vaaSRWU96d8qBwz9z2J_CObiV_H2-e8RezSK_sw0KISesp4czsOUlVKY",
                "review": None,
                "shipping": None,
                "source_transfer": None,
                "statement_descriptor": None,
                "statement_descriptor_suffix": None,
                "status": "succeeded",
                "transfer_data": None,
                "transfer_group": None,
            }
        },
    }
    webhook_table = pa.table(
        {
            "team_id": [team.id],
            "schema_id": [str(schema.id)],
            "payload_json": [orjson.dumps(webhook_event).decode("utf-8")],
        }
    )
    webhook_prefix = f"source_webhook_producer/{team.id}/{schema.id}"
    webhook_file_key = f"{webhook_prefix}/webhook_0.parquet"

    buf = pa.BufferOutputStream()
    pq.write_table(webhook_table, buf)
    await minio_client.put_object(
        Bucket=BUCKET_NAME,
        Key=webhook_file_key,
        Body=buf.getvalue().to_pybytes(),
    )

    files = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=webhook_prefix)
    assert len(files.get("Contents", [])) == 1

    # Run the pipeline again to ingest the webhook parquet
    with mock.patch.object(DeltaTableHelper, "compact_table"):
        workflow_id = str(uuid.uuid4())
        await _execute_run(workflow_id, inputs, stripe_charge["data"])

        await _replay_v3_consumer(team_id=team.pk, schema_id=schema.id)

    # Verify job completed
    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED

    # Verify webhook data was ingested alongside the original charge
    res = await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_charge", team)
    assert len(res.results) == 2

    # Verify webhook parquet file was deleted from S3 after consumption
    files = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=webhook_prefix)
    assert files.get("Contents") is None or len(files.get("Contents", [])) == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_webhook_consumer_e2e(team, stripe_charge, mock_stripe_client, minio_client):
    # 1. Initial sync to create delta table and mark initial_sync_complete
    _, inputs = await _run(
        team=team,
        schema_name=STRIPE_CHARGE_RESOURCE_NAME,
        table_name="stripe_charge",
        source_type="Stripe",
        job_inputs={
            "auth_method": {"selection": "api_key", "stripe_secret_key": "test-key"},
            "stripe_account_id": "acct_id",
        },
        mock_data_response=stripe_charge["data"],
        sync_type=ExternalDataSchema.SyncType.WEBHOOK,
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_charge", team)
    assert len(res.results) == 1

    # 2. Create a webhook HogFunction linked to this schema
    schema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)
    schema_id_str = str(schema.id)
    await sync_to_async(HogFunction.objects.create)(
        team=team,
        enabled=True,
        deleted=False,
        type="warehouse_source_webhook",
        inputs_schema=[{"key": "schema_mapping", "type": "json"}, {"key": "source_id", "type": "string"}],
        inputs={
            "schema_mapping": {"value": {"charge": schema_id_str}},
            "source_id": {"value": str(inputs.external_data_source_id)},
        },
    )

    assert schema.initial_sync_complete is True

    # 3. Simulate the Kafka message that would be produced by the Node.js webhook handler
    webhook_event = {
        "id": "evt_abc123",
        "type": "charge.refunded",
        "created": 1775760601,
        "data": {
            "object": {
                "id": "ch_abc123",
                "amount": 5000,
                "amount_refunded": 5000,
                "refunded": True,
                "object": "charge",
                "amount_captured": 1099,
                "application": None,
                "application_fee": None,
                "application_fee_amount": None,
                "balance_transaction": "txn_3MmlLrLkdIwHu7ix0uke3Ezy",
                "billing_details": {
                    "address": {
                        "city": None,
                        "country": None,
                        "line1": None,
                        "line2": None,
                        "postal_code": None,
                        "state": None,
                    },
                    "email": None,
                    "name": None,
                    "phone": None,
                },
                "calculated_statement_descriptor": "Stripe",
                "captured": True,
                "created": 1679090539,
                "currency": "usd",
                "customer": None,
                "description": None,
                "disputed": False,
                "failure_balance_transaction": None,
                "failure_code": None,
                "failure_message": None,
                "fraud_details": {},
                "invoice": None,
                "livemode": False,
                "metadata": {},
                "on_behalf_of": None,
                "outcome": {
                    "network_status": "approved_by_network",
                    "reason": None,
                    "risk_level": "normal",
                    "risk_score": 32,
                    "seller_message": "Payment complete.",
                    "type": "authorized",
                },
                "paid": True,
                "payment_intent": None,
                "payment_method": "card_1MmlLrLkdIwHu7ixIJwEWSNR",
                "payment_method_details": {
                    "card": {
                        "brand": "visa",
                        "checks": {"address_line1_check": None, "address_postal_code_check": None, "cvc_check": None},
                        "country": "US",
                        "exp_month": 3,
                        "exp_year": 2024,
                        "fingerprint": "mToisGZ01V71BCos",
                        "funding": "credit",
                        "installments": None,
                        "last4": "4242",
                        "mandate": None,
                        "network": "visa",
                        "three_d_secure": None,
                        "wallet": None,
                    },
                    "type": "card",
                },
                "receipt_email": None,
                "receipt_number": None,
                "receipt_url": "https://pay.stripe.com/receipts/payment/CAcaFwoVYWNjdF8xTTJKVGtMa2RJd0h1N2l4KOvG06AGMgZfBXyr1aw6LBa9vaaSRWU96d8qBwz9z2J_CObiV_H2-e8RezSK_sw0KISesp4czsOUlVKY",
                "review": None,
                "shipping": None,
                "source_transfer": None,
                "statement_descriptor": None,
                "statement_descriptor_suffix": None,
                "status": "succeeded",
                "transfer_data": None,
                "transfer_group": None,
            }
        },
    }

    kafka_message_value = orjson.dumps(
        {
            "team_id": team.id,
            "schema_id": schema_id_str,
            "payload": orjson.dumps(webhook_event).decode("utf-8"),
        }
    )

    # 4. Feed the raw Kafka message through the consumer's processing and flush,
    #    following the same pattern as _replay_v3_consumer (exercise processing logic
    #    directly rather than mocking the Kafka transport layer)
    config = WebhookConsumerConfig(
        input_topic="test-webhooks",
        consumer_group="test-group",
        dlq_topic="test-dlq",
    )

    consumer = WebhookS3Sink(config=config)
    consumer._consumer = mock.MagicMock()

    with override_settings(
        BUCKET_URL=f"s3://{BUCKET_NAME}",
        BUCKET_PATH=BUCKET_NAME,
        DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
        DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        DATAWAREHOUSE_BUCKET=BUCKET_NAME,
    ):
        consumer._process_message(kafka_message_value)
        assert consumer._buffer.total_messages == 1

        await sync_to_async(consumer._flush_all)("test")

    # 5. Verify the consumer wrote a parquet file to S3
    webhook_prefix = f"source_webhook_producer/{team.id}/{schema.id}"
    files = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=webhook_prefix)
    parquet_files = files.get("Contents", [])
    assert len(parquet_files) == 1
    assert parquet_files[0]["Key"].endswith(".parquet")

    # Verify offsets were committed
    consumer._consumer.commit.assert_called_once_with(asynchronous=False)

    # 6. Run the import pipeline to ingest the parquet
    with mock.patch.object(DeltaTableHelper, "compact_table"):
        workflow_id = str(uuid.uuid4())
        await _execute_run(workflow_id, inputs, stripe_charge["data"])

        await _replay_v3_consumer(team_id=team.pk, schema_id=schema.id)

    # 7. Verify job completed
    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED

    # 8. Verify webhook data was ingested alongside the original charge
    res = await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_charge", team)
    assert len(res.results) == 2

    # 9. Verify webhook parquet file was cleaned up after consumption
    files = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=webhook_prefix)
    assert files.get("Contents") is None or len(files.get("Contents", [])) == 0


async def _mysql_setup(mysql_connection, statements: list[tuple[str, tuple | None]]) -> None:
    """Run a list of `(sql, args)` statements against MySQL in one shot.

    `mysql_connection` is a sync pymysql connection; wrap the batch in
    `sync_to_async` so the surrounding async test body doesn't block the
    event loop.
    """

    def _run() -> None:
        with mysql_connection.cursor() as cursor:
            for sql_stmt, args in statements:
                cursor.execute(sql_stmt, args) if args is not None else cursor.execute(sql_stmt)
        mysql_connection.commit()

    await sync_to_async(_run)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mysql_full_refresh(team, mysql_config, mysql_connection):
    """Full-refresh sync of a simple table with a mix of common MySQL types."""
    await _mysql_setup(
        mysql_connection,
        [
            ("DROP TABLE IF EXISTS users_full_refresh", None),
            (
                """
                CREATE TABLE users_full_refresh (
                    id INT PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    age SMALLINT,
                    created_at DATETIME
                )
                """,
                None,
            ),
            (
                "INSERT INTO users_full_refresh (id, email, age, created_at) VALUES (%s, %s, %s, %s)",
                (1, "alice@example.com", 30, datetime(2025, 1, 1, 12, 0, 0)),
            ),
        ],
    )

    await _run(
        team=team,
        schema_name="users_full_refresh",
        table_name="mysql_users_full_refresh",
        source_type="MySQL",
        job_inputs=_mysql_job_inputs(mysql_config),
        mock_data_response=[],
    )

    res = await sync_to_async(execute_hogql_query)("SELECT id, email, age FROM mysql_users_full_refresh", team)
    assert res.results is not None
    row = res.results[0]
    assert row[0] == 1
    assert row[1] == "alice@example.com"
    assert row[2] == 30


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mysql_incremental_integer_cursor(team, mysql_config, mysql_connection):
    """Incremental sync with an INT cursor field — second run should pick up only new rows."""
    await _mysql_setup(
        mysql_connection,
        [
            ("DROP TABLE IF EXISTS events_int_incremental", None),
            (
                "CREATE TABLE events_int_incremental (id INT PRIMARY KEY, payload VARCHAR(64))",
                None,
            ),
            ("INSERT INTO events_int_incremental VALUES (1, 'first')", None),
        ],
    )

    _workflow_id, inputs = await _run(
        team=team,
        schema_name="events_int_incremental",
        table_name="mysql_events_int_incremental",
        source_type="MySQL",
        job_inputs=_mysql_job_inputs(mysql_config),
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT id FROM mysql_events_int_incremental ORDER BY id", team)
    assert [row[0] for row in res.results] == [1]

    # Insert more rows and re-run — the incremental cursor should pick them up.
    await _mysql_setup(
        mysql_connection,
        [
            ("INSERT INTO events_int_incremental VALUES (2, 'second')", None),
            ("INSERT INTO events_int_incremental VALUES (3, 'third')", None),
        ],
    )

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    res = await sync_to_async(execute_hogql_query)("SELECT id FROM mysql_events_int_incremental ORDER BY id", team)
    assert [row[0] for row in res.results] == [1, 2, 3]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mysql_full_refresh_with_zero_date(team, mysql_config, mysql_connection):
    """Full-refresh sync of a table containing MySQL's notorious
    '0000-00-00 00:00:00' zero-date. `_safe_convert_datetime` should map
    it to None so the sync survives pymysql's default type coercion."""
    await _mysql_setup(
        mysql_connection,
        [
            ("DROP TABLE IF EXISTS events_zero_date", None),
            ("CREATE TABLE events_zero_date (id INT PRIMARY KEY, updated_at DATETIME)", None),
            # Bypass strict mode to allow the zero datetime.
            ("SET SESSION sql_mode = ''", None),
            ("INSERT INTO events_zero_date VALUES (1, '0000-00-00 00:00:00')", None),
        ],
    )

    await _run(
        team=team,
        schema_name="events_zero_date",
        table_name="mysql_events_zero_date",
        source_type="MySQL",
        job_inputs=_mysql_job_inputs(mysql_config),
        mock_data_response=[],
    )

    res = await sync_to_async(execute_hogql_query)(
        "SELECT id, updated_at FROM mysql_events_zero_date",
        team,
    )
    assert len(res.results) == 1
    assert res.results[0][0] == 1
    # The zero date should have been converted to NULL/None.
    assert res.results[0][1] is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mysql_schema_evolution(team, mysql_config, mysql_connection):
    """Add a column between syncs — the second run should pick up the new column."""
    await _mysql_setup(
        mysql_connection,
        [
            ("DROP TABLE IF EXISTS orders_evolution", None),
            ("CREATE TABLE orders_evolution (id INT PRIMARY KEY)", None),
            ("INSERT INTO orders_evolution (id) VALUES (1)", None),
        ],
    )

    _workflow_id, inputs = await _run(
        team=team,
        schema_name="orders_evolution",
        table_name="mysql_orders_evolution",
        source_type="MySQL",
        job_inputs=_mysql_job_inputs(mysql_config),
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM mysql_orders_evolution", team)
    assert any(col == "id" for col in res.columns or [])

    await _mysql_setup(
        mysql_connection,
        [
            ("ALTER TABLE orders_evolution ADD COLUMN total_cents INT", None),
            ("INSERT INTO orders_evolution (id, total_cents) VALUES (2, 999)", None),
        ],
    )

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    res = await sync_to_async(execute_hogql_query)("SELECT * FROM mysql_orders_evolution", team)
    columns = res.columns or []
    assert any(col == "id" for col in columns)
    assert any(col == "total_cents" for col in columns)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_mysql_decimal_and_unsigned_types(team, mysql_config, mysql_connection):
    """DECIMAL(p,s) keeps precision; UNSIGNED BIGINT widens so the full
    u64 range (beyond signed int64) survives the round-trip."""
    await _mysql_setup(
        mysql_connection,
        [
            ("DROP TABLE IF EXISTS ledger_types", None),
            (
                """
                CREATE TABLE ledger_types (
                    id INT PRIMARY KEY,
                    amount DECIMAL(10, 2),
                    big_count BIGINT UNSIGNED
                )
                """,
                None,
            ),
            (
                "INSERT INTO ledger_types (id, amount, big_count) VALUES (%s, %s, %s)",
                (1, "123.45", 9_000_000_000_000_000_000),
            ),
        ],
    )

    await _run(
        team=team,
        schema_name="ledger_types",
        table_name="mysql_ledger_types",
        source_type="MySQL",
        job_inputs=_mysql_job_inputs(mysql_config),
        mock_data_response=[],
    )

    res = await sync_to_async(execute_hogql_query)(
        "SELECT id, amount, big_count FROM mysql_ledger_types",
        team,
    )
    rows = res.results
    assert rows is not None and len(rows) == 1
    assert rows[0][0] == 1
    # Decimal round-trip — compare as string to avoid float drift.
    assert str(rows[0][1]) == "123.45"
    # Unsigned BIGINT > signed-int64 max — must come back intact.
    assert int(rows[0][2]) == 9_000_000_000_000_000_000


def _postgres_job_inputs(postgres_config: dict) -> dict[str, str | dict[str, str]]:
    return {
        "host": postgres_config["host"],
        "port": postgres_config["port"],
        "database": postgres_config["database"],
        "user": postgres_config["user"],
        "password": postgres_config["password"],
        "schema": postgres_config["schema"],
        "ssh_tunnel_enabled": "False",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_xmin_sync(team, postgres_config, postgres_connection):
    """End-to-end xmin replication: initial snapshot, incremental delta on insert/update,
    persisted ceiling state, and hard-delete invisibility."""
    schema_name = postgres_config["schema"]
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.xmin_table (id integer PRIMARY KEY, name text)".format(schema=schema_name)
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.xmin_table (id, name) VALUES (1, 'a')".format(schema=schema_name)
    )
    await postgres_connection.commit()

    # Initial snapshot captures the committed row (`_run` asserts exactly one row landed).
    _workflow_id, inputs = await _run(
        team=team,
        schema_name="xmin_table",
        table_name="postgres_xmin_table",
        source_type="Postgres",
        job_inputs=_postgres_job_inputs(postgres_config),
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.XMIN,
        sync_type_config={},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT id, name FROM postgres_xmin_table ORDER BY id", team)
    assert [(r[0], r[1]) for r in res.results] == [(1, "a")]

    # Ceiling state persisted at job completion (next run's lower bound + durable cursor + epoch).
    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.xmin_last_value is not None
    assert schema.xmin_ceiling is not None
    assert schema.xmin_num_wraparound is not None
    first_ceiling = schema.xmin_last_value

    # Mutate: update the existing row and insert a new one. Both get a fresh xmin above the ceiling.
    await postgres_connection.execute(
        "UPDATE {schema}.xmin_table SET name = 'a2' WHERE id = 1".format(schema=schema_name)
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.xmin_table (id, name) VALUES (2, 'b')".format(schema=schema_name)
    )
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # Only the delta is read, upserted by primary key: row 1 reflects the update, row 2 is new.
    res = await sync_to_async(execute_hogql_query)("SELECT id, name FROM postgres_xmin_table ORDER BY id", team)
    assert [(r[0], r[1]) for r in res.results] == [(1, "a2"), (2, "b")]

    # Ceiling advanced strictly past the first run's value — the delta committed new transactions.
    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.xmin_last_value is not None
    assert schema.xmin_last_value > first_ceiling

    # Hard deletes are invisible to xmin — a vacuumed tuple leaves nothing to read.
    await postgres_connection.execute("DELETE FROM {schema}.xmin_table WHERE id = 2".format(schema=schema_name))
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    res = await sync_to_async(execute_hogql_query)("SELECT id, name FROM postgres_xmin_table ORDER BY id", team)
    assert [(r[0], r[1]) for r in res.results] == [(1, "a2"), (2, "b")]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_xmin_wraparound_or_range(team, postgres_config, postgres_connection):
    """The single-wrap `>= lower OR < upper` predicate executes against real Postgres and reads rows.
    A mocked ceiling forces the wraparound branch (the exact SQL is covered by unit tests)."""
    schema_name = postgres_config["schema"]
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.xmin_wrap (id integer PRIMARY KEY, name text)".format(schema=schema_name)
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.xmin_wrap (id, name) VALUES (1, 'a')".format(schema=schema_name)
    )
    await postgres_connection.commit()

    # Force the OR-range branch with a huge `upper` so the `< upper` side matches every real
    # (small) tuple xmin — exercising the wraparound predicate end-to-end.
    wraparound_bounds = XminBounds(
        lower=4_000_000_000,
        upper=4_294_967_295,
        ceiling_xid8=(1 << 32) | 4_294_967_295,
        num_wraparound=1,
        wraparound_or_range=True,
    )

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres._capture_xmin_ceiling",
        return_value=wraparound_bounds,
    ) as mock_capture:
        await _run(
            team=team,
            schema_name="xmin_wrap",
            table_name="postgres_xmin_wrap",
            source_type="Postgres",
            job_inputs=_postgres_job_inputs(postgres_config),
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={},
        )

    mock_capture.assert_called_once()

    res = await sync_to_async(execute_hogql_query)("SELECT id, name FROM postgres_xmin_wrap ORDER BY id", team)
    assert [(r[0], r[1]) for r in res.results] == [(1, "a")]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_switch_to_xmin_rebuilds_table(team, postgres_config, postgres_connection):
    """Switching an already-synced table to xmin rebuilds the Delta table. Without the resync the
    write fails: the old physical schema lacks the non-nullable `_ph_xmin` control column."""
    schema_name = postgres_config["schema"]
    await postgres_connection.execute(
        "CREATE TABLE IF NOT EXISTS {schema}.switch_tbl (id integer PRIMARY KEY, name text)".format(schema=schema_name)
    )
    await postgres_connection.execute(
        "INSERT INTO {schema}.switch_tbl (id, name) VALUES (1, 'a')".format(schema=schema_name)
    )
    await postgres_connection.commit()

    # First sync as incremental — the Delta table is created without `_ph_xmin`.
    _workflow_id, inputs = await _run(
        team=team,
        schema_name="switch_tbl",
        table_name="postgres_switch_tbl",
        source_type="Postgres",
        job_inputs=_postgres_job_inputs(postgres_config),
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "id", "incremental_field_type": "integer"},
    )

    res = await sync_to_async(execute_hogql_query)("SELECT id, name FROM postgres_switch_tbl ORDER BY id", team)
    assert [(r[0], r[1]) for r in res.results] == [(1, "a")]

    # Switch to xmin with reset_pipeline — what the serializer sets when crossing the xmin boundary.
    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    schema.sync_type = ExternalDataSchema.SyncType.XMIN
    schema.sync_type_config = {"primary_key_columns": ["id"], "reset_pipeline": True}
    await sync_to_async(schema.save)()

    await postgres_connection.execute(
        "INSERT INTO {schema}.switch_tbl (id, name) VALUES (2, 'b')".format(schema=schema_name)
    )
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])
    await _replay_v3_consumer(team_id=team.pk, schema_id=inputs.external_data_schema_id)

    # The table was rebuilt from scratch under xmin (first xmin run reads everything below the
    # ceiling), so both rows land and the `_ph_xmin` column is present.
    res = await sync_to_async(execute_hogql_query)(
        "SELECT id, name, _ph_xmin FROM postgres_switch_tbl ORDER BY id", team
    )
    assert [(r[0], r[1]) for r in res.results] == [(1, "a"), (2, "b")]
    assert all(r[2] is not None for r in res.results)

    # Reset consumed: xmin state seeded fresh, reset_pipeline cleared.
    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.sync_type_config.get("reset_pipeline") is None
    assert schema.xmin_last_value is not None
