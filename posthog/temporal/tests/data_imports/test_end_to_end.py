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

from posthog.hogql_queries.insights.funnels.funnel import Funnel
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.models import DataWarehouseTable
from posthog.models.team.team import Team
from posthog.temporal.common.shutdown import ShutdownMonitor, WorkerShuttingDownError
from posthog.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from posthog.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineNonDLT
from posthog.temporal.data_imports.row_tracking import get_rows
from posthog.temporal.data_imports.settings import ACTIVITIES
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
        mock.patch(
            "posthog.temporal.data_imports.pipelines.pipeline.pipeline.trigger_compaction_job"
        ) as mock_trigger_compaction_job,
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

        mock_trigger_compaction_job.assert_called()
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
    funnel_class = Funnel(context=FunnelQueryContext(query=query, team=team))

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
        "posthog.temporal.data_imports.workflow_activities.check_billing_limits.list_limited_team_attributes",
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
        "posthog.temporal.data_imports.workflow_activities.check_billing_limits.list_limited_team_attributes",
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
            "posthog.temporal.data_imports.workflow_activities.check_billing_limits.list_limited_team_attributes",
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
            "posthog.temporal.data_imports.workflow_activities.check_billing_limits.list_limited_team_attributes",
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
            {"id": "4112492", "domain_names": "transfer"},
            {"id": "4112492", "domain_names": ["transfer", "another_value"]},
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

    # Using datetime partition mode with created_at
    assert any(f"{PARTITION_KEY}=2025-01" in obj["Key"] for obj in s3_objects["Contents"])
    assert any(f"{PARTITION_KEY}=2025-02" in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["created_at"]
    assert schema.partition_mode == "datetime"
    assert schema.partition_format == "month"
    assert schema.partition_count is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_partition_folders_with_uuid_id_and_created_at_with_day_format(
    team, postgres_config, postgres_connection, minio_client
):
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
        "INSERT INTO {schema}.test_partition_folders (id, created_at) VALUES ('{uuid}', '2025-01-02T12:00:00.000Z')".format(
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

    # Set the parition format on the schema - this will persist after a reset_pipeline
    schema: ExternalDataSchema = await sync_to_async(ExternalDataSchema.objects.get)(id=inputs.external_data_schema_id)
    schema.sync_type_config["partition_format"] = "day"
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

    s3_objects = await minio_client.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{folder_path}/test_partition_folders/")

    # Using datetime partition mode with created_at - formatted to the day
    assert any(f"{PARTITION_KEY}=2025-01-01" in obj["Key"] for obj in s3_objects["Contents"])
    assert any(f"{PARTITION_KEY}=2025-01-02" in obj["Key"] for obj in s3_objects["Contents"])

    schema = await ExternalDataSchema.objects.aget(id=inputs.external_data_schema_id)
    assert schema.partitioning_enabled is True
    assert schema.partitioning_keys == ["created_at"]
    assert schema.partition_mode == "datetime"
    assert schema.partition_format == "day"
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
async def test_worker_shutdown_desc_sort_order(team, stripe_price, mock_stripe_client):
    """Testing that a descending sort ordered source will not trigger the rescheduling"""

    def mock_raise_if_is_worker_shutdown(self):
        raise WorkerShuttingDownError("test_id", "test_type", "test_queue", 1, "test_workflow", "test_workflow_type")

    with (
        mock.patch.object(ShutdownMonitor, "raise_if_is_worker_shutdown", mock_raise_if_is_worker_shutdown),
        mock.patch(
            "posthog.temporal.data_imports.external_data_job.trigger_schedule_buffer_one"
        ) as mock_trigger_schedule_buffer_one,
        mock.patch.object(PipelineNonDLT, "_chunk_size", 1),
    ):
        _, inputs = await _run(
            team=team,
            schema_name=STRIPE_PRICE_RESOURCE_NAME,
            table_name="stripe_price",
            source_type="Stripe",
            job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
            mock_data_response=stripe_price["data"],
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
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
        mock.patch.object(PipelineNonDLT, "_chunk_size", 1),
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
        mock.patch.object(PipelineNonDLT, "_chunk_size_bytes", 1),
        mock.patch.object(PipelineNonDLT, "_chunk_size", 5000),  # Explicitly make this big
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
