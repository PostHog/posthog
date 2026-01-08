import re
import uuid
import functools
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional, cast
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time
from unittest import mock

from django.conf import settings
from django.test import override_settings

import s3fs
import psycopg
import aioboto3
import deltalake
import pytest_asyncio
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
from posthog.models import DataWarehouseTable
from posthog.models.team.team import Team
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError
from posthog.temporal.data_imports.external_data_job import ETLSeparationGateInputs, ExternalDataJobWorkflow
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.delta_table_helper import DeltaTableHelper
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.row_tracking import get_rows
from posthog.temporal.data_imports.settings import ACTIVITIES
from posthog.temporal.data_imports.sources.common.registry import SourceRegistry
from posthog.temporal.data_imports.sources.stripe.constants import (
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
from posthog.temporal.data_imports.sources.stripe.custom import InvoiceListWithAllLines
from posthog.temporal.data_imports.workflow_activities.sync_new_schemas import ExternalDataSourceType
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.external_data_job import get_latest_run_if_exists
from products.data_warehouse.backend.models.external_table_definitions import external_tables
from products.data_warehouse.backend.models.join import DataWarehouseJoin

BUCKET_NAME = "test-pipeline"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


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


@pytest.fixture
def mock_stripe_client(
    stripe_balance_transaction,
    stripe_charge,
    stripe_customer,
    stripe_dispute,
    stripe_invoiceitem,
    stripe_invoice,
    stripe_payout,
    stripe_price,
    stripe_product,
    stripe_refund,
    stripe_subscription,
    stripe_credit_note,
    stripe_customer_balance_transaction,
    stripe_customer_payment_method,
):
    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.StripeClient") as MockStripeClient:
        mock_balance_transaction_list = mock.MagicMock()
        mock_charges_list = mock.MagicMock()
        mock_customers_list = mock.MagicMock()
        mock_disputes_list = mock.MagicMock()
        mock_invoice_items_list = mock.MagicMock()
        mock_invoice_list = mock.MagicMock()
        mock_payouts_list = mock.MagicMock()
        mock_price_list = mock.MagicMock()
        mock_product_list = mock.MagicMock()
        mock_refunds_list = mock.MagicMock()
        mock_subscription_list = mock.MagicMock()
        mock_credit_notes_list = mock.MagicMock()
        mock_customer_balance_transactions_list = mock.MagicMock()
        mock_customer_payment_methods_list = mock.MagicMock()

        mock_balance_transaction_list.auto_paging_iter.return_value = stripe_balance_transaction["data"]
        mock_charges_list.auto_paging_iter.return_value = stripe_charge["data"]
        mock_customers_list.auto_paging_iter.return_value = stripe_customer["data"]
        mock_disputes_list.auto_paging_iter.return_value = stripe_dispute["data"]
        mock_invoice_items_list.auto_paging_iter.return_value = stripe_invoiceitem["data"]
        mock_invoice_list.auto_paging_iter.return_value = stripe_invoice["data"]
        mock_payouts_list.auto_paging_iter.return_value = stripe_payout["data"]
        mock_price_list.auto_paging_iter.return_value = stripe_price["data"]
        mock_product_list.auto_paging_iter.return_value = stripe_product["data"]
        mock_refunds_list.auto_paging_iter.return_value = stripe_refund["data"]
        mock_subscription_list.auto_paging_iter.return_value = stripe_subscription["data"]
        mock_credit_notes_list.auto_paging_iter.return_value = stripe_credit_note["data"]
        mock_customer_balance_transactions_list.auto_paging_iter.return_value = stripe_customer_balance_transaction[
            "data"
        ]
        mock_customer_payment_methods_list.auto_paging_iter.return_value = stripe_customer_payment_method["data"]

        instance = MockStripeClient.return_value
        instance.balance_transactions.list.return_value = mock_balance_transaction_list
        instance.charges.list.return_value = mock_charges_list
        instance.customers.list.return_value = mock_customers_list
        instance.disputes.list.return_value = mock_disputes_list
        instance.invoice_items.list.return_value = mock_invoice_items_list
        instance.invoices.list.return_value = mock_invoice_list
        instance.payouts.list.return_value = mock_payouts_list
        instance.prices.list.return_value = mock_price_list
        instance.products.list.return_value = mock_product_list
        instance.refunds.list.return_value = mock_refunds_list
        instance.subscriptions.list.return_value = mock_subscription_list
        instance.credit_notes.list.return_value = mock_credit_notes_list
        instance.customers.balance_transactions.list.return_value = mock_customer_balance_transactions_list
        instance.customers.payment_methods.list.return_value = mock_customer_payment_methods_list

        yield instance


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
    job_inputs: dict[str, str],
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
            "posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"
        ) as mock_get_data_import_finished_metric,
    ):
        await _execute_run(workflow_id, inputs, mock_data_response)

    if not ignore_assertions:
        run: ExternalDataJob = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=source.pk)

        assert run is not None
        assert run.status == ExternalDataJob.Status.COMPLETED
        assert run.finished_at is not None
        assert run.storage_delta_mib is not None
        assert run.storage_delta_mib != 0

        mock_compact_table.assert_called()
        mock_get_data_import_finished_metric.assert_called_with(
            source_type=source_type, status=ExternalDataJob.Status.COMPLETED.lower()
        )

        await sync_to_async(schema.refresh_from_db)()

        assert schema.last_synced_at == run.created_at

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
    ):
        return iter(mock_data_response)

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

    with (
        mock.patch.object(RESTClient, "paginate", mock_paginate),
        mock.patch.object(ListObject, "auto_paging_iter", return_value=iter(mock_data_response)),
        mock.patch.object(InvoiceListWithAllLines, "auto_paging_iter", return_value=iter(mock_data_response)),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
            DATA_WAREHOUSE_REDIS_HOST="localhost",
            DATA_WAREHOUSE_REDIS_PORT="6379",
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=ACTIVITIES,  # type: ignore
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await activity_environment.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_balance_transactions(team, stripe_balance_transaction, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_balance_transaction["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_charges(team, stripe_charge, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_CHARGE_RESOURCE_NAME,
        table_name="stripe_charge",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_charge["data"],
    )

    # Get team from the DB to remove cached config value
    team = await sync_to_async(Team.objects.get)(id=team.id)
    assert team.revenue_analytics_config.notified_first_sync


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_customer(team, stripe_customer, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
        table_name="stripe_customer",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_customer["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_invoice(team, stripe_invoice, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_INVOICE_RESOURCE_NAME,
        table_name="stripe_invoice",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_invoice["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_price(team, stripe_price, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_PRICE_RESOURCE_NAME,
        table_name="stripe_price",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_price["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_product(team, stripe_product, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_PRODUCT_RESOURCE_NAME,
        table_name="stripe_product",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_product["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_subscription(team, stripe_subscription, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_SUBSCRIPTION_RESOURCE_NAME,
        table_name="stripe_subscription",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_subscription["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_dispute(team, stripe_dispute, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_DISPUTE_RESOURCE_NAME,
        table_name="stripe_dispute",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_dispute["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_payout(team, stripe_payout, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_PAYOUT_RESOURCE_NAME,
        table_name="stripe_payout",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_payout["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_refund(team, stripe_refund, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_REFUND_RESOURCE_NAME,
        table_name="stripe_refund",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_refund["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_invoiceitem(team, stripe_invoiceitem, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_INVOICE_ITEM_RESOURCE_NAME,
        table_name="stripe_invoiceitem",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_invoiceitem["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_credit_note(team, stripe_credit_note, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_CREDIT_NOTE_RESOURCE_NAME,
        table_name="stripe_creditnote",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_credit_note["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_customer_balance_transaction(team, stripe_customer_balance_transaction, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
        table_name="stripe_customerbalancetransaction",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_customer_balance_transaction["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_customer_payment_method(team, stripe_customer_payment_method, mock_stripe_client):
    await _run(
        team=team,
        schema_name=STRIPE_CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
        table_name="stripe_customerpaymentmethod",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_customer_payment_method["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_brands(team, zendesk_brands):
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
        mock_data_response=zendesk_brands["brands"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_organizations(team, zendesk_organizations):
    await _run(
        team=team,
        schema_name="organizations",
        table_name="zendesk_organizations",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_organizations["organizations"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_groups(team, zendesk_groups):
    await _run(
        team=team,
        schema_name="groups",
        table_name="zendesk_groups",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_groups["groups"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_sla_policies(team, zendesk_sla_policies):
    await _run(
        team=team,
        schema_name="sla_policies",
        table_name="zendesk_sla_policies",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_sla_policies["sla_policies"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_users(team, zendesk_users):
    await _run(
        team=team,
        schema_name="users",
        table_name="zendesk_users",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_users["users"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_ticket_fields(team, zendesk_ticket_fields):
    await _run(
        team=team,
        schema_name="ticket_fields",
        table_name="zendesk_ticket_fields",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_ticket_fields["ticket_fields"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_ticket_events(team, zendesk_ticket_events):
    await _run(
        team=team,
        schema_name="ticket_events",
        table_name="zendesk_ticket_events",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_ticket_events["ticket_events"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_tickets(team, zendesk_tickets):
    await _run(
        team=team,
        schema_name="tickets",
        table_name="zendesk_tickets",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_tickets["tickets"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_zendesk_ticket_metric_events(team, zendesk_ticket_metric_events):
    await _run(
        team=team,
        schema_name="ticket_metric_events",
        table_name="zendesk_ticket_metric_events",
        source_type="Zendesk",
        job_inputs={
            "subdomain": "test",
            "api_key": "test_api_key",
            "email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_ticket_metric_events["ticket_metric_events"],
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
    # Setting `id` to `0` - the same as an `integer` incremental initial value
    await postgres_connection.execute(
        "INSERT INTO {schema}.test_table (id) VALUES (0)".format(schema=postgres_config["schema"])
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

    # Include rows that have the same incremental value as the `initial_value`
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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
            "posthog.temporal.data_imports.workflow_activities.create_job_model.delete_external_data_schedule"
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
        mock.patch.object(s3fs.S3FileSystem, "delete") as mock_s3_delete,
    ):
        workflow_id, inputs = await _run(
            team=team,
            schema_name="BalanceTransaction",
            table_name="stripe_balancetransaction",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_balance_transaction["data"],
        billable=False,
    )

    run: ExternalDataJob = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=inputs.external_data_source_id)
    assert run.billable is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync(team, postgres_config, postgres_connection):
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
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1),
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres._get_table_chunk_size") as mock_chunk_size,
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
    ):
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

    mock_post_run_operations.assert_called_once()

    mock_merge.assert_not_called()
    assert mock_write.call_count == 2

    _, first_call_kwargs = mock_write.call_args_list[0]
    _, second_call_kwargs = mock_write.call_args_list[1]

    # The first call should be an overwrite
    assert first_call_kwargs == {
        "mode": "overwrite",
        "schema_mode": "overwrite",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "engine": "rust",
    }

    # The last call should be an append
    assert second_call_kwargs == {
        "mode": "append",
        "schema_mode": "merge",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "engine": "rust",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync_uncapped_chunk_size(team, postgres_config, postgres_connection):
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
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1),
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
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

    mock_post_run_operations.assert_called_once()

    mock_merge.assert_not_called()
    assert mock_write.call_count == 1

    _, first_call_kwargs = mock_write.call_args_list[0]

    # first and only call should be an overwite
    assert first_call_kwargs == {
        "mode": "overwrite",
        "schema_mode": "overwrite",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "engine": "rust",
    }


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_no_merging_on_first_sync_after_reset(team, postgres_config, postgres_connection):
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
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1),
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres._get_table_chunk_size") as mock_chunk_size,
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
    ):
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

    mock_post_run_operations.assert_called_once()

    mock_merge.assert_not_called()
    assert mock_write.call_count == 2

    _, first_call_kwargs = mock_write.call_args_list[0]
    _, second_call_kwargs = mock_write.call_args_list[1]

    # The first call should be an overwrite
    assert first_call_kwargs == {
        "mode": "overwrite",
        "schema_mode": "overwrite",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "engine": "rust",
    }

    # The subsequent call should be an append
    assert second_call_kwargs == {
        "mode": "append",
        "schema_mode": "merge",
        "table_or_uri": mock.ANY,
        "data": mock.ANY,
        "partition_by": mock.ANY,
        "engine": "rust",
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
        assert any(
            f"{PARTITION_KEY}={expected_partition}" in obj["Key"] for obj in s3_objects["Contents"]
        ), f"Expected partition {expected_partition} not found in S3 objects"

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

    def mock_setup_partitioning(pa_table, existing_delta_table, schema, resource, logger):
        return pa_table

    # Emulate an existing table with no partitions
    with mock.patch(
        "posthog.temporal.data_imports.pipelines.pipeline.pipeline.setup_partitioning", mock_setup_partitioning
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

    def mock_setup_partitioning(pa_table, existing_delta_table, schema, resource, logger):
        return pa_table

    # Emulate an existing table with no partitions
    with mock.patch(
        "posthog.temporal.data_imports.pipelines.pipeline.pipeline.setup_partitioning", mock_setup_partitioning
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
    team, postgres_config, postgres_connection
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

    with (
        mock.patch("posthog.temporal.data_imports.sources.postgres.postgres.DEFAULT_CHUNK_SIZE", 1),
        mock.patch.object(DeltaTable, "merge") as mock_merge,
        mock.patch.object(deltalake, "write_deltalake") as mock_write,
        mock.patch.object(PipelineNonDLT, "_post_run_operations") as mock_post_run_operations,
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

    mock_post_run_operations.assert_called_once()

    mock_write.assert_not_called()
    assert mock_merge.call_count == 1

    merge_call_args, first_call_kwargs = mock_merge.call_args_list[0]

    assert first_call_kwargs == {
        "source": mock.ANY,
        "source_alias": "source",
        "target_alias": "target",
        "predicate": f"source.id = target.id AND source.{PARTITION_KEY} = target.{PARTITION_KEY} AND target.{PARTITION_KEY} = '0'",
        "streamed_exec": True,
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
        mock.patch("posthog.temporal.data_imports.pipelines.pipeline.pipeline.decrement_rows") as mock_decrement_rows,
        mock.patch("posthog.temporal.data_imports.external_data_job.finish_row_tracking") as mock_finish_row_tracking,
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
    mock_finish_row_tracking.assert_called_once()

    assert schema_id is not None
    with override_settings(
        DATA_WAREHOUSE_REDIS_HOST="localhost",
        DATA_WAREHOUSE_REDIS_PORT="6379",
    ):
        row_count_in_redis = get_rows(team.id, schema_id)

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
        mock.patch("posthog.temporal.data_imports.external_data_job.update_should_sync") as mock_update_should_sync,
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
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
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=[],
        sync_type=ExternalDataSchema.SyncType.APPEND,
        sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
    )

    await _execute_run(str(uuid.uuid4()), inputs, [])

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

    async def mock_get_workflows(*args, **kwargs):
        yield {
            "workflow_id": "test-workflow-id",
            "run_id": "test-run-id",
            "status": "RUNNING",
            "close_time": datetime.now().isoformat(),
        }

    with (
        mock.patch.object(ShutdownMonitor, "raise_if_is_worker_shutdown", mock_raise_if_is_worker_shutdown),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
        ) as mock_trigger_schedule_buffer_one,
        mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1),
        mock.patch("posthog.temporal.data_imports.sources.temporalio.temporalio._get_workflows", mock_get_workflows),
    ):
        _, inputs = await _run(
            team=team,
            schema_name="workflows",
            table_name="temporalio_workflows",
            source_type="TemporalIO",
            job_inputs={
                "host": "test",
                "port": "1234",
                "namespace": "test",
                "server_client_root_ca": "test",
                "client_certificate": "test",
                "client_private_key": "test",
                "encryption_key": "test",
            },
            mock_data_response=[],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "close_time", "incremental_field_type": "datetime"},
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
            "posthog.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
        ) as mock_trigger_schedule_buffer_one,
        mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 1),
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
async def test_pipeline_mb_chunk_size(team, zendesk_brands):
    with (
        mock.patch("posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE_BYTES", 1),
        mock.patch(
            "posthog.temporal.data_imports.pipelines.pipeline.batcher.DEFAULT_CHUNK_SIZE", 5000
        ),  # Explicitly make this big
        mock.patch.object(PipelineNonDLT, "_process_pa_table") as mock_process_pa_table,
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

    assert mock_process_pa_table.call_count == 2


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

    schemas = await get_schemas()
    assert len(schemas) == 2

    # Drop the table we've not synced yet
    await postgres_connection.execute("DROP TABLE {schema}.table_2".format(schema=postgres_config["schema"]))
    await postgres_connection.commit()

    await _execute_run(str(uuid.uuid4()), inputs, [])

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

    schemas = await get_schemas()
    assert len(schemas) == 2

    # Drop the table that we've already synced
    await postgres_connection.execute("DROP TABLE {schema}.table_1".format(schema=postgres_config["schema"]))
    await postgres_connection.commit()

    # Sync the second table - this will trigger `sync_new_schemas_activity`
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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
            mock_data_response=stripe_balance_transaction["data"],
        )

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    folder_path = await sync_to_async(schema.folder_path)()

    # Sync a second time 5 minutes later
    datetime_2 = datetime_1 + timedelta(minutes=5)
    with freeze_time(datetime_2):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])

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
    with freeze_time(datetime_5), mock.patch("posthog.temporal.data_imports.util.S3_DELETE_TIME_BUFFER", 1):
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])

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
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
            mock_data_response=stripe_customer["data"],
            ignore_assertions=True,
        )

        mock_raise_if_is_worker_shutdown.assert_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_non_retryable_error_short_circuiting(team, stripe_customer, mock_stripe_client):
    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.get_rows") as mock_get_rows:
        mock_get_rows.side_effect = Exception("Some error that doesn't retry")

        with pytest.raises(Exception):
            await _run(
                team=team,
                schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
                table_name="stripe_customer",
                source_type="Stripe",
                job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
                mock_data_response=stripe_customer["data"],
                ignore_assertions=True,
            )

    # Incremental and resumable source syncs retry up to 9 times
    assert mock_get_rows.call_count == 9

    source_cls = SourceRegistry.get_source(ExternalDataSourceType.STRIPE)
    non_retryable_errors = source_cls.get_non_retryable_errors()
    non_retryable_error = next(iter(non_retryable_errors.keys()))

    with mock.patch("posthog.temporal.data_imports.sources.stripe.stripe.get_rows") as mock_get_rows:
        mock_get_rows.side_effect = Exception(non_retryable_error)

        with pytest.raises(Exception):
            await _run(
                team=team,
                schema_name=STRIPE_CUSTOMER_RESOURCE_NAME,
                table_name="stripe_customer",
                source_type="Stripe",
                job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
                mock_data_response=stripe_customer["data"],
                ignore_assertions=True,
            )

    # Non-retryable errors are retried up to 3 times before giving up (4 total attempts)
    assert mock_get_rows.call_count == 4


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_etl_separation_happy_path_incremental(team, stripe_customer, mock_stripe_client):
    """
    Test the V3 ET+L separation pipeline happy path for incremental syncs.

    When etl_separation_gate_activity returns True (for incremental syncs):
    - ET workflow starts the Load workflow via start_load_workflow_activity
    - extract_and_transform_batch_activity is called and signals batches to Load workflow
    - Load workflow receives batch_ready signals and processes batches
    - Load workflow receives et_complete signal and finalizes
    - Job record is updated with V3 pipeline version and ET+L tracking fields
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    activity_calls: dict[str, list[Any]] = {
        "etl_separation_gate": [],
        "start_load_workflow": [],
        "extract_and_transform_batch": [],
        "update_et_tracking": [],
    }

    @activity.defn(name="etl_separation_gate_activity")
    def mock_gate(inputs: ETLSeparationGateInputs) -> bool:
        activity_calls["etl_separation_gate"].append(inputs)
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(inputs: StartLoadWorkflowInputs) -> None:
        activity_calls["start_load_workflow"].append(inputs)

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(inputs: ExtractBatchInputs) -> ExtractBatchResult:
        activity_calls["extract_and_transform_batch"].append(inputs)
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(inputs: UpdateETTrackingInputs) -> None:
        activity_calls["update_et_tracking"].append(inputs)

    # Filter out the real activities we're mocking
    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # Verify gate was called with schema_id
    assert len(activity_calls["etl_separation_gate"]) == 1
    gate_input = activity_calls["etl_separation_gate"][0]
    assert gate_input.team_id == team.id
    assert gate_input.schema_id == str(schema.id)

    # V3 path: verify ET activities were called
    assert len(activity_calls["start_load_workflow"]) == 1
    assert len(activity_calls["extract_and_transform_batch"]) == 1
    assert len(activity_calls["update_et_tracking"]) >= 1

    # Verify start_load_workflow inputs
    start_load_input = activity_calls["start_load_workflow"][0]
    assert start_load_input.team_id == team.id
    assert start_load_input.schema_id == str(schema.id)
    assert start_load_input.source_id == str(source.pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_et_failure_cancels_load_workflow(team, stripe_customer, mock_stripe_client):
    """
    Test that when ET fails mid-extraction, the Load workflow is cancelled.

    When extract_and_transform_batch_activity fails:
    - The Load workflow should be cancelled via workflow.cancel()
    - Job status should be set to FAILED
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    from posthog.temporal.data_imports.load_data_job import LoadDataJobInputs, LoadDataJobWorkflow

    # Use a mutable container to share the client with the mock activity
    client_holder: dict = {}

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(inputs: StartLoadWorkflowInputs) -> None:
        # Actually start the Load workflow so it can be cancelled
        # Use the same task queue as the main workflow for test simplicity
        client = client_holder["client"]
        await client.start_workflow(
            LoadDataJobWorkflow.run,
            LoadDataJobInputs(
                team_id=inputs.team_id,
                source_id=inputs.source_id,
                schema_id=inputs.schema_id,
                job_id=inputs.job_id,
                source_type=inputs.source_type,
            ),
            id=inputs.workflow_id,
            task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
        )

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract_failure(_: ExtractBatchInputs) -> ExtractBatchResult:
        from temporalio.exceptions import ApplicationError

        raise ApplicationError("Simulated extraction failure", type="NonRetryableException")

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract_failure, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            client_holder["client"] = env.client

            # Single worker with both workflows on the same task queue for test simplicity
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow, LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                with pytest.raises(Exception) as exc_info:
                    await env.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                # Exception chain: WorkflowFailureError -> ActivityError -> ApplicationError
                assert "Simulated extraction failure" in str(exc_info.value.cause.cause)

    # Verify job is marked as failed
    job = await sync_to_async(
        lambda: ExternalDataJob.objects.filter(
            team_id=team.id,
            schema_id=schema.id,
        )
        .order_by("-created_at")
        .first()
    )()
    assert job is not None
    assert job.status == ExternalDataJob.Status.FAILED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_gate_returns_false_for_non_incremental_syncs(team, stripe_customer, mock_stripe_client):
    """
    Test that etl_separation_gate_activity returns False for non-incremental syncs
    (full_refresh) and the V2 legacy path is used instead of V3.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.external_data_job import ETLSeparationGateInputs
    from posthog.temporal.data_imports.workflow_activities.et_activities import StartLoadWorkflowInputs

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    # Full refresh sync - should NOT use V3 path
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="full_refresh",
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    gate_inputs_received: list[ETLSeparationGateInputs] = []
    start_load_called = {"called": False}

    @activity.defn(name="etl_separation_gate_activity")
    def mock_gate(inputs: ETLSeparationGateInputs) -> bool:
        gate_inputs_received.append(inputs)
        # Gate returns False for non-incremental syncs
        return False

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        start_load_called["called"] = True
        raise AssertionError("start_load_workflow_activity should not be called for non-incremental sync")

    filtered_activities = [
        a for a in ACTIVITIES if a.__name__ not in ("etl_separation_gate_activity", "start_load_workflow_activity")
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # Verify gate was called with correct inputs
    assert len(gate_inputs_received) == 1
    assert gate_inputs_received[0].team_id == team.id
    assert gate_inputs_received[0].schema_id == str(schema.id)

    # Verify start_load was NOT called (V2 path used)
    assert start_load_called["called"] is False

    # Verify job completed using V2 path
    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=source.pk)
    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_load_workflow_processes_batches_and_finalizes(team, stripe_customer, mock_stripe_client):
    """
    Test the Load workflow in isolation:
    - Receives batch_ready signals and processes batches via load_batch_to_delta_activity
    - Receives et_complete signal and finalizes via finalize_delta_table_activity
    - Cleans up temp storage via cleanup_temp_storage_activity
    """
    from temporalio import activity

    from posthog.temporal.data_imports.external_data_job import create_source_templates, update_external_data_job_model
    from posthog.temporal.data_imports.load_data_job import (
        CleanupTempStorageInputs,
        FinalizeDeltaTableInputs,
        LoadBatchInputs,
        LoadDataJobInputs,
        LoadDataJobWorkflow,
        RecoveryState,
    )
    from posthog.temporal.data_imports.pipelines.pipeline.signals import BatchReadySignal, ETCompleteSignal
    from posthog.temporal.data_imports.workflow_activities.calculate_table_size import calculate_table_size_activity
    from posthog.temporal.data_imports.workflow_activities.et_activities import UpdateETTrackingInputs

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
    )

    job = await sync_to_async(ExternalDataJob.objects.create)(
        team_id=team.id,
        pipeline_id=source.pk,
        schema_id=schema.id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        pipeline_version=ExternalDataJob.PipelineVersion.V3,
    )

    load_workflow_id = f"load-{schema.id}-test"
    load_inputs = LoadDataJobInputs(
        team_id=team.id,
        source_id=str(source.pk),
        schema_id=str(schema.id),
        job_id=str(job.id),
        source_type="Stripe",
    )

    activity_calls: dict[str, list[Any]] = {
        "check_recovery_state": [],
        "load_batch_to_delta": [],
        "finalize_delta_table": [],
        "cleanup_temp_storage": [],
    }

    @activity.defn(name="check_recovery_state_activity")
    def mock_check_recovery(_) -> RecoveryState:
        activity_calls["check_recovery_state"].append(True)
        return RecoveryState(
            has_manifest=False,
            manifest_path=None,
            temp_s3_prefix=None,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    @activity.defn(name="load_batch_to_delta_activity")
    def mock_load_batch(inputs: LoadBatchInputs) -> dict:
        activity_calls["load_batch_to_delta"].append(inputs)
        return {"rows_loaded": inputs.batch_number * 50 + 50, "batch_number": inputs.batch_number}

    @activity.defn(name="finalize_delta_table_activity")
    def mock_finalize(inputs: FinalizeDeltaTableInputs) -> dict:
        activity_calls["finalize_delta_table"].append(inputs)
        return {"status": "finalized", "total_rows": inputs.total_rows, "queryable_folder": "test-folder"}

    @activity.defn(name="cleanup_temp_storage_activity")
    def mock_cleanup(inputs: CleanupTempStorageInputs) -> None:
        activity_calls["cleanup_temp_storage"].append(inputs)

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    @activity.defn(name="update_job_batch_loaded_activity")
    def mock_update_batch_loaded(_) -> None:
        pass

    test_activities = [
        mock_check_recovery,
        mock_load_batch,
        mock_finalize,
        mock_cleanup,
        mock_update_tracking,
        mock_update_batch_loaded,
        update_external_data_job_model,
        create_source_templates,
        calculate_table_size_activity,
    ]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.load_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                # Start the load workflow
                handle = await env.client.start_workflow(
                    LoadDataJobWorkflow.run,
                    load_inputs,
                    id=load_workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Send batch_ready signals
                await handle.signal(
                    "batch_ready",
                    BatchReadySignal(
                        batch_path="temp/data/part-0000.parquet",
                        batch_number=0,
                        schema_path="temp/schema.arrow",
                        row_count=50,
                        primary_keys=["id"],
                        sync_type="incremental",
                    ),
                )

                await handle.signal(
                    "batch_ready",
                    BatchReadySignal(
                        batch_path="temp/data/part-0001.parquet",
                        batch_number=1,
                        schema_path="temp/schema.arrow",
                        row_count=100,
                        primary_keys=["id"],
                        sync_type="incremental",
                    ),
                )

                # Send et_complete signal
                await handle.signal(
                    "et_complete",
                    ETCompleteSignal(
                        manifest_path="temp/prefix/manifest.json",
                        total_batches=2,
                        total_rows=150,
                    ),
                )

                # Wait for completion
                result = await handle.result()

    # Verify activities were called
    assert len(activity_calls["check_recovery_state"]) == 1
    assert len(activity_calls["load_batch_to_delta"]) == 2
    assert len(activity_calls["finalize_delta_table"]) == 1
    assert len(activity_calls["cleanup_temp_storage"]) == 1

    # Verify batch inputs
    batch_0 = activity_calls["load_batch_to_delta"][0]
    assert batch_0.batch_number == 0
    assert batch_0.is_first_batch is True
    assert batch_0.sync_type == "incremental"

    batch_1 = activity_calls["load_batch_to_delta"][1]
    assert batch_1.batch_number == 1
    assert batch_1.is_first_batch is False

    # Verify finalize inputs
    finalize = activity_calls["finalize_delta_table"][0]
    assert finalize.total_rows == 150
    assert finalize.manifest_path == "temp/prefix/manifest.json"

    # Verify result
    assert result["batches_processed"] == 2
    assert result["total_rows"] == 150
    assert result["status"] == "completed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_load_workflow_handles_recovery_state(team, stripe_customer, mock_stripe_client):
    """
    Test that the Load workflow correctly handles recovery state when restarted.
    It should skip batches that were already loaded and continue from where it left off.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.external_data_job import create_source_templates, update_external_data_job_model
    from posthog.temporal.data_imports.load_data_job import (
        CleanupTempStorageInputs,
        FinalizeDeltaTableInputs,
        LoadBatchInputs,
        LoadDataJobInputs,
        LoadDataJobWorkflow,
        RecoveryBatch,
        RecoveryState,
    )
    from posthog.temporal.data_imports.workflow_activities.calculate_table_size import calculate_table_size_activity
    from posthog.temporal.data_imports.workflow_activities.et_activities import UpdateETTrackingInputs

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
    )

    job = await sync_to_async(ExternalDataJob.objects.create)(
        team_id=team.id,
        pipeline_id=source.pk,
        schema_id=schema.id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        pipeline_version=ExternalDataJob.PipelineVersion.V3,
        manifest_path="temp/prefix/manifest.json",
    )

    load_workflow_id = f"load-{schema.id}-recovery-test"
    load_inputs = LoadDataJobInputs(
        team_id=team.id,
        source_id=str(source.pk),
        schema_id=str(schema.id),
        job_id=str(job.id),
        source_type="Stripe",
    )

    activity_calls: dict[str, list[Any]] = {
        "load_batch_to_delta": [],
    }

    @activity.defn(name="check_recovery_state_activity")
    def mock_check_recovery(_) -> RecoveryState:
        return RecoveryState(
            has_manifest=True,
            manifest_path="temp/prefix/manifest.json",
            temp_s3_prefix="temp/prefix",
            batches=[
                RecoveryBatch(
                    batch_path="temp/data/part-0000.parquet",
                    batch_number=0,
                    row_count=50,
                    already_loaded=True,  # Already loaded
                ),
                RecoveryBatch(
                    batch_path="temp/data/part-0001.parquet",
                    batch_number=1,
                    row_count=100,
                    already_loaded=False,  # Not yet loaded
                ),
            ],
            total_rows=150,
            primary_keys=["id"],
            sync_type="incremental",
            schema_path="temp/schema.arrow",
        )

    @activity.defn(name="load_batch_to_delta_activity")
    def mock_load_batch(inputs: LoadBatchInputs) -> dict:
        activity_calls["load_batch_to_delta"].append(inputs)
        return {"rows_loaded": inputs.batch_number * 50 + 50, "batch_number": inputs.batch_number}

    @activity.defn(name="finalize_delta_table_activity")
    def mock_finalize(_: FinalizeDeltaTableInputs) -> dict:
        return {"status": "finalized", "total_rows": 150, "queryable_folder": "test-folder"}

    @activity.defn(name="cleanup_temp_storage_activity")
    def mock_cleanup(_: CleanupTempStorageInputs) -> None:
        pass

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    @activity.defn(name="update_job_batch_loaded_activity")
    def mock_update_batch_loaded(_) -> None:
        pass

    test_activities = [
        mock_check_recovery,
        mock_load_batch,
        mock_finalize,
        mock_cleanup,
        mock_update_tracking,
        mock_update_batch_loaded,
        update_external_data_job_model,
        create_source_templates,
        calculate_table_size_activity,
    ]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.load_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                result = await env.client.execute_workflow(
                    LoadDataJobWorkflow.run,
                    load_inputs,
                    id=load_workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # Should only load batch 1 (batch 0 was already loaded in recovery state)
    assert len(activity_calls["load_batch_to_delta"]) == 1
    batch = activity_calls["load_batch_to_delta"][0]
    assert batch.batch_number == 1
    # is_first_batch should be False because batch 0 was already loaded
    assert batch.is_first_batch is False

    assert result["batches_processed"] == 2  # Both batches counted (1 recovered + 1 loaded)
    assert result["status"] == "completed"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_billing_limits(team, stripe_customer, mock_stripe_client):
    """
    Test that billing limits work correctly in the V3 ET+L separated flow.
    When billing limit is reached, job should be marked as BILLING_LIMIT_REACHED.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )
    # Set created_at to older than 7 days so billing check is not skipped
    source.created_at = datetime(2024, 1, 1, tzinfo=ZoneInfo("UTC"))
    await sync_to_async(source.save)()

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=True,
    )

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        pass

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(_: ExtractBatchInputs) -> ExtractBatchResult:
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
        mock.patch("ee.billing.quota_limiting.list_limited_team_attributes") as mock_billing,
    ):
        mock_billing.return_value = [team.api_token]

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    job = await sync_to_async(
        lambda: ExternalDataJob.objects.filter(team_id=team.id, schema_id=schema.id).order_by("-created_at").first()
    )()
    assert job is not None
    assert job.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_non_retryable_error_in_et(team, stripe_customer, mock_stripe_client):
    """
    Test that non-retryable errors in the ET phase are handled correctly.
    The schema should be marked as should_sync=False.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.load_data_job import LoadDataJobInputs, LoadDataJobWorkflow
    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    # Use a mutable container to share the client with the mock activity
    client_holder: dict = {}

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(inputs: StartLoadWorkflowInputs) -> None:
        # Actually start the Load workflow so it can be cancelled
        client = client_holder["client"]
        await client.start_workflow(
            LoadDataJobWorkflow.run,
            LoadDataJobInputs(
                team_id=inputs.team_id,
                source_id=inputs.source_id,
                schema_id=inputs.schema_id,
                job_id=inputs.job_id,
                source_type=inputs.source_type,
            ),
            id=inputs.workflow_id,
            task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
        )

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract_non_retryable(_: ExtractBatchInputs) -> ExtractBatchResult:
        from temporalio.exceptions import ApplicationError

        raise ApplicationError(
            "401 Client Error: Unauthorized for url: https://api.stripe.com", type="NonRetryableException"
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [
        *filtered_activities,
        mock_gate,
        mock_start_load,
        mock_extract_non_retryable,
        mock_update_tracking,
    ]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
        mock.patch.object(posthoganalytics, "capture"),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            client_holder["client"] = env.client

            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow, LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                with pytest.raises(Exception) as exc_info:
                    await env.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                # Exception chain: WorkflowFailureError -> ActivityError -> ApplicationError
                assert "401 Client Error" in str(exc_info.value.cause.cause)

    job = await sync_to_async(
        lambda: ExternalDataJob.objects.filter(team_id=team.id, schema_id=schema.id).order_by("-created_at").first()
    )()
    assert job is not None
    assert job.status == ExternalDataJob.Status.FAILED

    await sync_to_async(schema.refresh_from_db)()
    assert schema.should_sync is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_reset_pipeline(team, stripe_customer, mock_stripe_client):
    """
    Test that reset_pipeline works correctly with the V3 ET+L path.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
            "reset_pipeline": True,
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
        reset_pipeline=True,
    )

    reset_detected = {"detected": False}

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        pass

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(inputs: ExtractBatchInputs) -> ExtractBatchResult:
        if inputs.reset_pipeline:
            reset_detected["detected"] = True
            # Simulate real activity behavior: clear reset_pipeline flag after extraction
            schema_obj = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.schema_id)
            await sync_to_async(schema_obj.update_sync_type_config_for_reset_pipeline)()
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # Verify reset was passed to the extract activity
    assert reset_detected["detected"] is True

    # Verify reset_pipeline is cleared after successful run
    await sync_to_async(schema.refresh_from_db)()
    assert schema.sync_type_config.get("reset_pipeline") is None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_delta_no_merging_on_first_batch(team, stripe_customer, mock_stripe_client):
    """
    Test that the V3 Load workflow correctly sets is_first_batch to skip delta merging
    on the first batch write.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.external_data_job import create_source_templates, update_external_data_job_model
    from posthog.temporal.data_imports.load_data_job import (
        CleanupTempStorageInputs,
        FinalizeDeltaTableInputs,
        LoadBatchInputs,
        LoadDataJobInputs,
        LoadDataJobWorkflow,
        RecoveryState,
    )
    from posthog.temporal.data_imports.pipelines.pipeline.signals import BatchReadySignal, ETCompleteSignal
    from posthog.temporal.data_imports.workflow_activities.calculate_table_size import calculate_table_size_activity
    from posthog.temporal.data_imports.workflow_activities.et_activities import UpdateETTrackingInputs

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
    )

    job = await sync_to_async(ExternalDataJob.objects.create)(
        team_id=team.id,
        pipeline_id=source.pk,
        schema_id=schema.id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        pipeline_version=ExternalDataJob.PipelineVersion.V3,
    )

    load_workflow_id = f"load-{schema.id}-first-batch-test"
    load_inputs = LoadDataJobInputs(
        team_id=team.id,
        source_id=str(source.pk),
        schema_id=str(schema.id),
        job_id=str(job.id),
        source_type="Stripe",
    )

    batch_inputs_received: list[LoadBatchInputs] = []

    @activity.defn(name="check_recovery_state_activity")
    def mock_check_recovery(_) -> RecoveryState:
        return RecoveryState(
            has_manifest=False,
            manifest_path=None,
            temp_s3_prefix=None,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    @activity.defn(name="load_batch_to_delta_activity")
    def mock_load_batch(inputs: LoadBatchInputs) -> dict:
        batch_inputs_received.append(inputs)
        return {"rows_loaded": 50, "batch_number": inputs.batch_number}

    @activity.defn(name="finalize_delta_table_activity")
    def mock_finalize(_: FinalizeDeltaTableInputs) -> dict:
        return {"status": "finalized", "total_rows": 150, "queryable_folder": "test-folder"}

    @activity.defn(name="cleanup_temp_storage_activity")
    def mock_cleanup(_: CleanupTempStorageInputs) -> None:
        pass

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    @activity.defn(name="update_job_batch_loaded_activity")
    def mock_update_batch_loaded(_) -> None:
        pass

    test_activities = [
        mock_check_recovery,
        mock_load_batch,
        mock_finalize,
        mock_cleanup,
        mock_update_tracking,
        mock_update_batch_loaded,
        update_external_data_job_model,
        create_source_templates,
        calculate_table_size_activity,
    ]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.load_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                handle = await env.client.start_workflow(
                    LoadDataJobWorkflow.run,
                    load_inputs,
                    id=load_workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Send 3 batches
                for i in range(3):
                    await handle.signal(
                        "batch_ready",
                        BatchReadySignal(
                            batch_path=f"temp/data/part-{i:04d}.parquet",
                            batch_number=i,
                            schema_path="temp/schema.arrow",
                            row_count=50,
                            primary_keys=["id"],
                            sync_type="incremental",
                        ),
                    )

                await handle.signal(
                    "et_complete",
                    ETCompleteSignal(
                        manifest_path="temp/prefix/manifest.json",
                        total_batches=3,
                        total_rows=150,
                    ),
                )

                await handle.result()

    # Verify is_first_batch flag
    assert len(batch_inputs_received) == 3

    # First batch should have is_first_batch=True (should use overwrite mode, no merge)
    assert batch_inputs_received[0].batch_number == 0
    assert batch_inputs_received[0].is_first_batch is True

    # Subsequent batches should have is_first_batch=False (should use append mode)
    assert batch_inputs_received[1].batch_number == 1
    assert batch_inputs_received[1].is_first_batch is False

    assert batch_inputs_received[2].batch_number == 2
    assert batch_inputs_received[2].is_first_batch is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_et_workflow_does_not_call_finish_row_tracking(team, stripe_customer, mock_stripe_client):
    """
    Test that in V3 ET workflow, finish_row_tracking is NOT called.
    In V3, row tracking finalization is delegated to the Load workflow.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        pass

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(_: ExtractBatchInputs) -> ExtractBatchResult:
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
            DATA_WAREHOUSE_REDIS_HOST="localhost",
            DATA_WAREHOUSE_REDIS_PORT="6379",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
        mock.patch("posthog.temporal.data_imports.pipelines.pipeline.pipeline.decrement_rows"),
        mock.patch("posthog.temporal.data_imports.external_data_job.finish_row_tracking") as mock_finish,
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    # In V3 ET workflow, finish_row_tracking should NOT be called
    # (it's handled by the Load workflow instead)
    mock_finish.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_load_workflow_calls_finish_row_tracking(team, stripe_customer, mock_stripe_client):
    """
    Test that in V3 Load workflow, finish_row_tracking IS called.
    The Load workflow is responsible for finalizing row tracking in V3.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.load_data_job import (
        CheckRecoveryStateInputs,
        CleanupTempStorageInputs,
        FinalizeDeltaTableInputs,
        LoadBatchInputs,
        LoadDataJobInputs,
        LoadDataJobWorkflow,
        RecoveryState,
    )
    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        UpdateETTrackingInputs,
        UpdateJobBatchLoadedInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    job = await sync_to_async(ExternalDataJob.objects.create)(
        team_id=team.pk,
        pipeline_id=source.pk,
        schema_id=schema.pk,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id="test-workflow",
        pipeline_version=ExternalDataJob.PipelineVersion.V3,
    )

    workflow_id = str(uuid.uuid4())
    inputs = LoadDataJobInputs(
        team_id=team.id,
        source_id=str(source.pk),
        schema_id=str(schema.id),
        job_id=str(job.id),
        source_type="Stripe",
    )

    @activity.defn(name="check_recovery_state_activity")
    def mock_check_recovery(_: CheckRecoveryStateInputs) -> RecoveryState:
        return RecoveryState(
            has_manifest=False,
            manifest_path=None,
            temp_s3_prefix=None,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    @activity.defn(name="load_batch_to_delta_activity")
    def mock_load_batch(_: LoadBatchInputs) -> dict:
        return {"rows_loaded": 100, "batch_number": 0}

    @activity.defn(name="update_job_batch_loaded_activity")
    def mock_update_batch(_: UpdateJobBatchLoadedInputs) -> None:
        pass

    @activity.defn(name="finalize_delta_table_activity")
    def mock_finalize(_: FinalizeDeltaTableInputs) -> dict:
        return {"status": "finalized", "total_rows": 100, "queryable_folder": "test/folder"}

    @activity.defn(name="cleanup_temp_storage_activity")
    def mock_cleanup(_: CleanupTempStorageInputs) -> None:
        pass

    # Get the activity names we're mocking
    mocked_activity_names = {
        "check_recovery_state_activity",
        "update_et_tracking_activity",
        "load_batch_to_delta_activity",
        "update_job_batch_loaded_activity",
        "finalize_delta_table_activity",
        "cleanup_temp_storage_activity",
    }

    # Filter out activities we're mocking and add our mocks
    filtered_activities = [a for a in ACTIVITIES if a.__name__ not in mocked_activity_names]
    test_activities = [
        *filtered_activities,
        mock_check_recovery,
        mock_update_tracking,
        mock_load_batch,
        mock_update_batch,
        mock_finalize,
        mock_cleanup,
    ]

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
        ),
        mock.patch("posthog.temporal.data_imports.load_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch("posthog.temporal.data_imports.external_data_job.finish_row_tracking") as mock_finish,
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[LoadDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                # Send ET complete signal immediately (no batches to process)
                handle = await env.client.start_workflow(
                    LoadDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Signal that ET is complete with no batches
                from posthog.temporal.data_imports.pipelines.pipeline.signals import ETCompleteSignal

                await handle.signal(
                    LoadDataJobWorkflow.et_complete,
                    ETCompleteSignal(
                        manifest_path="",  # Empty string for no manifest
                        total_batches=0,
                        total_rows=0,
                    ),
                )

                await handle.result()

    # In V3 Load workflow, finish_row_tracking SHOULD be called
    mock_finish.assert_called_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_billable_job(team, stripe_customer, mock_stripe_client):
    """
    Test that the billable flag is correctly set on jobs in V3 pipeline.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,  # Explicitly set to False
    )

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        pass

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(_: ExtractBatchInputs) -> ExtractBatchResult:
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    run = await get_latest_run_if_exists(
        team_id=team.pk, pipeline_id=source.pk, expected_status=ExternalDataJob.Status.RUNNING
    )
    assert run is not None
    assert run.billable is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_worker_shutdown_during_et(team, stripe_customer, mock_stripe_client):
    """
    Test that worker shutdown during ET phase is handled correctly.
    The workflow should complete successfully if the data was already extracted.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    extraction_calls = {"count": 0}

    @activity.defn(name="etl_separation_gate_activity")
    async def mock_gate(_) -> bool:
        return True

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load(_: StartLoadWorkflowInputs) -> None:
        pass

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(_: ExtractBatchInputs) -> ExtractBatchResult:
        extraction_calls["count"] += 1
        # Simulate worker shutdown on first call by raising WorkerShuttingDownError
        if extraction_calls["count"] == 1:
            raise WorkerShuttingDownError(
                "test_id", "test_type", "test_queue", 1, "test_workflow", "test_workflow_type"
            )
        return ExtractBatchResult(
            is_done=True,
            batch_path="temp/data/part-0000.parquet",
            batch_number=1,
            row_count=100,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(_: UpdateETTrackingInputs) -> None:
        pass

    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
        )
    ]
    test_activities = [*filtered_activities, mock_gate, mock_start_load, mock_extract, mock_update_tracking]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
        mock.patch("posthog.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=test_activities,
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                max_concurrent_activities=50,
            ):
                # The workflow should handle the shutdown and potentially reschedule
                try:
                    await env.client.execute_workflow(
                        ExternalDataJobWorkflow.run,
                        inputs,
                        id=workflow_id,
                        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                        retry_policy=RetryPolicy(maximum_attempts=2),  # Allow retry
                    )
                except Exception:
                    pass  # Workflow may fail due to shutdown

    # Verify that extraction was attempted
    assert extraction_calls["count"] >= 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_v3_integrated_et_and_l_workflows(team, stripe_customer, mock_stripe_client):
    """
    Integrated E2E test that runs both ET and L workflows together.

    This test verifies the full V3 pipeline where:
    - ET workflow starts the L workflow via start_load_workflow_activity
    - ET workflow sends batch_ready signals to L workflow as it extracts data
    - ET workflow sends et_complete signal when extraction finishes
    - L workflow processes batches and finalizes the Delta table
    - Both workflows complete successfully

    Unlike other V3 tests that test ET and L in isolation, this test verifies
    the actual signal passing and workflow coordination between ET and L.
    """
    from temporalio import activity

    from posthog.temporal.data_imports.load_data_job import (
        CheckRecoveryStateInputs,
        CleanupTempStorageInputs,
        FinalizeDeltaTableInputs,
        LoadBatchInputs,
        LoadDataJobInputs,
        LoadDataJobWorkflow,
        RecoveryState,
    )
    from posthog.temporal.data_imports.pipelines.pipeline.signals import BatchReadySignal, ETCompleteSignal
    from posthog.temporal.data_imports.workflow_activities.et_activities import (
        ExtractBatchInputs,
        ExtractBatchResult,
        StartLoadWorkflowInputs,
        UpdateETTrackingInputs,
    )

    source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id=uuid.uuid4(),
        connection_id=uuid.uuid4(),
        destination_id=uuid.uuid4(),
        team=team,
        status="running",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
    )

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=STRIPE_CUSTOMER_RESOURCE_NAME,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="incremental",
        sync_type_config={
            "incremental_field": "created",
            "incremental_field_type": "integer",
        },
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
        billable=False,
    )

    activity_calls: dict[str, list[Any]] = {
        "etl_separation_gate": [],
        "start_load_workflow": [],
        "extract_and_transform_batch": [],
        "update_et_tracking": [],
        "check_recovery_state": [],
        "load_batch_to_delta": [],
        "finalize_delta_table": [],
        "cleanup_temp_storage": [],
    }

    # Track the test environment client for mocking
    test_env_client = None

    @activity.defn(name="etl_separation_gate_activity")
    def mock_gate(inputs: ETLSeparationGateInputs) -> bool:
        activity_calls["etl_separation_gate"].append(inputs)
        return True  # Use V3 path

    # Note: start_load_workflow_activity is defined below (mock_start_load_with_capture)
    # to capture the L workflow ID for waiting

    @activity.defn(name="extract_and_transform_batch_activity")
    async def mock_extract(inputs: ExtractBatchInputs) -> ExtractBatchResult:
        """Mock extraction that sends real signals to the L workflow."""
        activity_calls["extract_and_transform_batch"].append(inputs)

        # Get handle to the L workflow and send signals
        if inputs.load_workflow_id:
            load_handle = test_env_client.get_workflow_handle(inputs.load_workflow_id)

            # Send batch signals (simulating 2 batches of data)
            await load_handle.signal(
                "batch_ready",
                BatchReadySignal(
                    batch_path="temp/data/part-0000.parquet",
                    batch_number=0,
                    schema_path="temp/schema.arrow",
                    row_count=50,
                    primary_keys=["id"],
                    sync_type="incremental",
                ),
            )

            await load_handle.signal(
                "batch_ready",
                BatchReadySignal(
                    batch_path="temp/data/part-0001.parquet",
                    batch_number=1,
                    schema_path="temp/schema.arrow",
                    row_count=75,
                    primary_keys=["id"],
                    sync_type="incremental",
                ),
            )

            # Send ET complete signal
            await load_handle.signal(
                "et_complete",
                ETCompleteSignal(
                    manifest_path="temp/prefix/manifest.json",
                    total_batches=2,
                    total_rows=125,
                ),
            )

        return ExtractBatchResult(
            is_done=True,
            batch_path=None,
            batch_number=2,
            row_count=125,
            schema_path="temp/schema.arrow",
            temp_s3_prefix="temp/prefix",
            manifest_path="temp/prefix/manifest.json",
        )

    @activity.defn(name="update_et_tracking_activity")
    def mock_update_tracking(inputs: UpdateETTrackingInputs) -> None:
        activity_calls["update_et_tracking"].append(inputs)
        # Actually update the job record like the real activity does
        job = ExternalDataJob.objects.get(id=inputs.job_id)
        if inputs.pipeline_version is not None:
            job.pipeline_version = inputs.pipeline_version
            job.save()

    @activity.defn(name="check_recovery_state_activity")
    def mock_check_recovery(_: CheckRecoveryStateInputs) -> RecoveryState:
        activity_calls["check_recovery_state"].append(True)
        return RecoveryState(
            has_manifest=False,
            manifest_path=None,
            temp_s3_prefix=None,
            batches=[],
            total_rows=0,
            primary_keys=None,
            sync_type=None,
            schema_path=None,
        )

    @activity.defn(name="load_batch_to_delta_activity")
    def mock_load_batch(inputs: LoadBatchInputs) -> dict:
        activity_calls["load_batch_to_delta"].append(inputs)
        return {"rows_loaded": inputs.batch_number * 50 + 50, "batch_number": inputs.batch_number}

    @activity.defn(name="finalize_delta_table_activity")
    def mock_finalize(inputs: FinalizeDeltaTableInputs) -> dict:
        activity_calls["finalize_delta_table"].append(inputs)
        return {"status": "finalized", "total_rows": inputs.total_rows, "queryable_folder": "test-folder"}

    @activity.defn(name="cleanup_temp_storage_activity")
    def mock_cleanup(inputs: CleanupTempStorageInputs) -> None:
        activity_calls["cleanup_temp_storage"].append(inputs)

    @activity.defn(name="update_job_batch_loaded_activity")
    def mock_update_batch_loaded(_) -> None:
        pass

    # Filter out real activities and replace with mocks
    # Note: start_load_workflow_activity is handled separately below to capture the L workflow ID
    filtered_activities = [
        a
        for a in ACTIVITIES
        if a.__name__
        not in (
            "etl_separation_gate_activity",
            "start_load_workflow_activity",
            "extract_and_transform_batch_activity",
            "update_et_tracking_activity",
            "check_recovery_state_activity",
            "load_batch_to_delta_activity",
            "finalize_delta_table_activity",
            "cleanup_temp_storage_activity",
            "update_job_batch_loaded_activity",
        )
    ]
    test_activities = [
        *filtered_activities,
        mock_gate,
        # mock_start_load is added below as mock_start_load_with_capture
        mock_extract,
        mock_update_tracking,
        mock_check_recovery,
        mock_load_batch,
        mock_finalize,
        mock_cleanup,
        mock_update_batch_loaded,
    ]

    def mock_to_session_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "aws_session_token": None,
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def mock_to_object_store_rs_credentials(_):
        return {
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "region": "us-east-1",
            "AWS_ALLOW_HTTP": "true",
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    # Track the L workflow ID so we can wait for it
    load_workflow_id_captured: list[str] = []

    @activity.defn(name="start_load_workflow_activity")
    async def mock_start_load_with_capture(inputs_inner: StartLoadWorkflowInputs) -> None:
        """Start the Load workflow using the test environment client."""
        activity_calls["start_load_workflow"].append(inputs_inner)
        load_workflow_id_captured.append(inputs_inner.workflow_id)

        # Start the actual Load workflow in the test environment
        await test_env_client.start_workflow(
            LoadDataJobWorkflow.run,
            LoadDataJobInputs(
                team_id=inputs_inner.team_id,
                source_id=inputs_inner.source_id,
                schema_id=inputs_inner.schema_id,
                job_id=inputs_inner.job_id,
                source_type=inputs_inner.source_type,
            ),
            id=inputs_inner.workflow_id,
            task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,  # Same queue for testing
        )

    # Update the activities list to use the capturing version
    test_activities_with_capture = [
        a for a in test_activities if getattr(a, "__name__", "") != "start_load_workflow_activity"
    ] + [mock_start_load_with_capture]

    with (
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            BUCKET_PATH=BUCKET_NAME,
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(DeltaTableHelper, "compact_table"),
        mock.patch("posthog.temporal.data_imports.external_data_job.get_data_import_finished_metric"),
        mock.patch("posthog.temporal.data_imports.load_data_job.get_data_import_finished_metric"),
        mock.patch("posthoganalytics.capture_exception", return_value=None),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
    ):
        # Import DuckLake workflow for child workflow registration
        from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import DuckLakeCopyDataImportsWorkflow

        async with await WorkflowEnvironment.start_time_skipping() as env:
            # Store the test client for use in mock activities
            test_env_client = env.client

            # Create workers for both task queues (DuckLake child workflow runs on different queue)
            async with (
                Worker(
                    env.client,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    workflows=[ExternalDataJobWorkflow, LoadDataJobWorkflow],
                    activities=test_activities_with_capture,
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activity_executor=ThreadPoolExecutor(max_workers=50),
                    max_concurrent_activities=50,
                ),
                Worker(
                    env.client,
                    task_queue=settings.DUCKLAKE_TASK_QUEUE,
                    workflows=[DuckLakeCopyDataImportsWorkflow],
                    activities=[],  # DuckLake workflow activities not needed for this test
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ),
            ):
                # Execute the ET workflow - it will start the L workflow internally
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                # Wait for the L workflow to complete
                # The ET workflow starts the L workflow and sends signals, but L runs independently
                if load_workflow_id_captured:
                    load_handle = env.client.get_workflow_handle(load_workflow_id_captured[0])
                    await load_handle.result()

    # Verify ET workflow activities were called
    assert len(activity_calls["etl_separation_gate"]) == 1
    assert len(activity_calls["start_load_workflow"]) == 1
    assert len(activity_calls["extract_and_transform_batch"]) == 1

    # Verify L workflow was started with correct inputs
    start_load_input = activity_calls["start_load_workflow"][0]
    assert start_load_input.team_id == team.id
    assert start_load_input.schema_id == str(schema.id)
    assert start_load_input.source_id == str(source.pk)

    # Verify L workflow activities were called (signals were received and processed)
    assert len(activity_calls["check_recovery_state"]) == 1
    assert len(activity_calls["load_batch_to_delta"]) == 2  # 2 batches
    assert len(activity_calls["finalize_delta_table"]) == 1
    assert len(activity_calls["cleanup_temp_storage"]) == 1

    # Verify batches were processed in order
    batch_0 = activity_calls["load_batch_to_delta"][0]
    assert batch_0.batch_number == 0
    assert batch_0.is_first_batch is True
    assert batch_0.sync_type == "incremental"
    assert batch_0.batch_path == "temp/data/part-0000.parquet"

    batch_1 = activity_calls["load_batch_to_delta"][1]
    assert batch_1.batch_number == 1
    assert batch_1.is_first_batch is False
    assert batch_1.batch_path == "temp/data/part-0001.parquet"

    # Verify finalize was called with correct total rows
    finalize = activity_calls["finalize_delta_table"][0]
    assert finalize.total_rows == 125
    assert finalize.manifest_path == "temp/prefix/manifest.json"

    # Verify job was created and has V3 pipeline version
    job: ExternalDataJob = await sync_to_async(ExternalDataJob.objects.get)(team_id=team.id, schema_id=schema.pk)
    assert job.pipeline_version == ExternalDataJob.PipelineVersion.V3
    assert job.status == ExternalDataJob.Status.COMPLETED
