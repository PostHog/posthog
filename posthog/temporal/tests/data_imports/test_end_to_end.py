from typing import Any, Optional
from unittest import mock
import uuid
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
import pytest
from posthog.hogql.query import execute_hogql_query
from posthog.models.team.team import Team
from posthog.temporal.data_imports import ACTIVITIES
from posthog.temporal.data_imports.external_data_job import ExternalDataJobWorkflow
from posthog.temporal.utils import ExternalDataWorkflowInputs
from posthog.warehouse.models.external_table_definitions import external_tables
from posthog.warehouse.models import (
    ExternalDataJob,
    ExternalDataSource,
    ExternalDataSchema,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from posthog.constants import DATA_WAREHOUSE_TASK_QUEUE
from posthog.warehouse.models.external_data_job import get_latest_run_if_exists
from dlt.sources.helpers.rest_client.client import RESTClient


BUCKET_NAME = "test-pipeline"


async def _run(
    team: Team, schema_name: str, table_name: str, source_type: str, job_inputs: dict[str, str], mock_data_response: Any
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

    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        name=schema_name,
        team_id=team.pk,
        source_id=source.pk,
    )

    workflow_id = str(uuid.uuid4())
    inputs = ExternalDataWorkflowInputs(
        team_id=team.id,
        external_data_source_id=source.pk,
        external_data_schema_id=schema.id,
    )

    await _execute_run(workflow_id, inputs, mock_data_response)

    run = await get_latest_run_if_exists(team_id=team.pk, pipeline_id=source.pk)

    assert run is not None
    assert run.status == ExternalDataJob.Status.COMPLETED

    res = await sync_to_async(execute_hogql_query)(f"SELECT * FROM {table_name}", team)
    assert len(res.results) == 1

    for name, field in external_tables.get(table_name, {}).items():
        if field.hidden:
            continue
        assert name in (res.columns or [])

    await sync_to_async(source.refresh_from_db)()
    assert source.job_inputs.get("reset_pipeline", None) is None

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

    with (
        mock.patch.object(RESTClient, "paginate", mock_paginate),
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                workflows=[ExternalDataJobWorkflow],
                activities=ACTIVITIES,  # type: ignore
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await activity_environment.client.execute_workflow(  # type: ignore
                    ExternalDataJobWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=DATA_WAREHOUSE_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_balance_transactions(team, stripe_balance_transaction):
    await _run(
        team=team,
        schema_name="BalanceTransaction",
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_balance_transaction["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_charges(team, stripe_charge):
    await _run(
        team=team,
        schema_name="Charge",
        table_name="stripe_charge",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_charge["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_customer(team, stripe_customer):
    await _run(
        team=team,
        schema_name="Customer",
        table_name="stripe_customer",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_customer["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_invoice(team, stripe_invoice):
    await _run(
        team=team,
        schema_name="Invoice",
        table_name="stripe_invoice",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_invoice["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_price(team, stripe_price):
    await _run(
        team=team,
        schema_name="Price",
        table_name="stripe_price",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_price["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_product(team, stripe_product):
    await _run(
        team=team,
        schema_name="Product",
        table_name="stripe_product",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_product["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_stripe_subscription(team, stripe_subscription):
    await _run(
        team=team,
        schema_name="Subscription",
        table_name="stripe_subscription",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id"},
        mock_data_response=stripe_subscription["data"],
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
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
            "zendesk_subdomain": "test",
            "zendesk_api_key": "test_api_key",
            "zendesk_email_address": "test@posthog.com",
        },
        mock_data_response=zendesk_ticket_metric_events["ticket_metric_events"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_reset_pipeline(team, stripe_balance_transaction):
    await _run(
        team=team,
        schema_name="BalanceTransaction",
        table_name="stripe_balancetransaction",
        source_type="Stripe",
        job_inputs={"stripe_secret_key": "test-key", "stripe_account_id": "acct_id", "reset_pipeline": "True"},
        mock_data_response=stripe_balance_transaction["data"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_make_sure_deletions_occur(team, stripe_balance_transaction):
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
        job_ids = (
            ExternalDataJob.objects.filter(
                team_id=team.pk,
                pipeline_id=inputs.external_data_source_id,
            )
            .order_by("-created_at")
            .values_list("id", flat=True)
        )

        return [str(job_id) for job_id in job_ids]

    with mock.patch("posthog.warehouse.models.external_data_job.get_s3_client") as mock_s3_client:
        s3_client_mock = mock.Mock()
        mock_s3_client.return_value = s3_client_mock

        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])
        await _execute_run(workflow_id, inputs, stripe_balance_transaction["data"])

        job_ids = await get_jobs()
        latest_job = job_ids[0]
        assert s3_client_mock.exists.call_count == 3

        for call in s3_client_mock.exists.call_args_list:
            assert latest_job not in call[0][0]
