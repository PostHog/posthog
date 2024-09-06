from typing import Any, Optional
from unittest import mock
import aioboto3
import functools
import uuid
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
import pytest
import pytest_asyncio
import psycopg
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.insights.funnels.funnel import Funnel
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.models.team.team import Team
from posthog.schema import (
    BreakdownFilter,
    BreakdownType,
    EventsNode,
    FunnelsQuery,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
)
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
from dlt.common.configuration.specs.aws_credentials import AwsCredentials

from posthog.warehouse.models.join import DataWarehouseJoin


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


@pytest_asyncio.fixture
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
        sync_type=sync_type,
        sync_type_config=sync_type_config or {},
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
        override_settings(
            BUCKET_URL=f"s3://{BUCKET_NAME}",
            AIRBYTE_BUCKET_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            AIRBYTE_BUCKET_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            AIRBYTE_BUCKET_REGION="us-east-1",
            AIRBYTE_BUCKET_DOMAIN="objectstorage:19000",
        ),
        mock.patch.object(AwsCredentials, "to_session_credentials", mock_to_session_credentials),
        mock.patch.object(AwsCredentials, "to_object_store_rs_credentials", mock_to_object_store_rs_credentials),
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
    assert len(columns) == 3
    assert columns[0] == "id"
    assert columns[1] == "_dlt_id"
    assert columns[2] == "_dlt_load_id"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_delta_wrapper_files(team, stripe_balance_transaction, minio_client):
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
        Bucket=BUCKET_NAME, Prefix=f"{folder_path}/balance_transaction__query/"
    )

    assert len(s3_objects["Contents"]) != 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_funnels_lazy_joins_ordering(team, stripe_customer):
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
    assert len(columns) == 3
    assert any(x == "id" for x in columns)
    assert any(x == "_dlt_id" for x in columns)
    assert any(x == "_dlt_load_id" for x in columns)

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
    assert len(columns) == 4
    assert any(x == "id" for x in columns)
    assert any(x == "new_col" for x in columns)
    assert any(x == "_dlt_id" for x in columns)
    assert any(x == "_dlt_load_id" for x in columns)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sql_database_missing_incremental_values(team, postgres_config, postgres_connection):
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
    assert len(columns) == 3
    assert any(x == "id" for x in columns)
    assert any(x == "_dlt_id" for x in columns)
    assert any(x == "_dlt_load_id" for x in columns)

    # Exclude rows that don't have the incremental cursor key set
    assert len(res.results) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_sql_database_incremental_initual_value(team, postgres_config, postgres_connection):
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
    assert len(columns) == 3
    assert any(x == "id" for x in columns)
    assert any(x == "_dlt_id" for x in columns)
    assert any(x == "_dlt_load_id" for x in columns)

    # Include rows that have the same incremental value as the `initial_value`
    assert len(res.results) == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_billing_limits(team, stripe_customer):
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

    assert job.status == ExternalDataJob.Status.CANCELLED

    with pytest.raises(Exception):
        await sync_to_async(execute_hogql_query)("SELECT * FROM stripe_customer", team)
