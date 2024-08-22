from typing import Any
from unittest import mock
import pytest
from asgiref.sync import sync_to_async
from posthog.models.team.team import Team
from posthog.temporal.data_imports.workflow_activities.import_data import ImportDataActivityInputs, import_data_activity
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.models.table import DataWarehouseTable


async def _setup(team: Team, job_inputs: dict[Any, Any]) -> ImportDataActivityInputs:
    source = await sync_to_async(ExternalDataSource.objects.create)(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSource.Type.POSTGRES,
        job_inputs=job_inputs,
    )
    credentials = await sync_to_async(DataWarehouseCredential.objects.create)(
        access_key="blah", access_secret="blah", team=team
    )
    warehouse_table = await sync_to_async(DataWarehouseTable.objects.create)(
        name="table_1",
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
    )
    schema = await sync_to_async(ExternalDataSchema.objects.create)(
        team=team,
        name="table_1",
        source=source,
        table=warehouse_table,
        should_sync=True,
        status=ExternalDataSchema.Status.COMPLETED,
        last_synced_at="2024-01-01",
    )
    job = await sync_to_async(ExternalDataJob.objects.create)(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id="some_workflow_id",
    )

    return ImportDataActivityInputs(team_id=team.pk, schema_id=schema.pk, source_id=source.pk, run_id=str(job.pk))


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_source_without_ssh_tunnel(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
    }

    activity_inputs = await _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.sql_database.sql_source_for_type") as sql_source_for_type,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data._run"),
    ):
        await activity_environment.run(import_data_activity, activity_inputs)

        sql_source_for_type.assert_called_once_with(
            source_type=ExternalDataSource.Type.POSTGRES,
            host="host.com",
            port="5432",
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            incremental_field=None,
            incremental_field_type=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_source_with_ssh_tunnel_disabled(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
        "ssh_tunnel_enabled": "False",
        "ssh_tunnel_host": "",
        "ssh_tunnel_port": "",
    }

    activity_inputs = await _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.sql_database.sql_source_for_type") as sql_source_for_type,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data._run"),
    ):
        await activity_environment.run(import_data_activity, activity_inputs)

        sql_source_for_type.assert_called_once_with(
            source_type=ExternalDataSource.Type.POSTGRES,
            host="host.com",
            port="5432",
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            incremental_field=None,
            incremental_field_type=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_postgres_source_with_ssh_tunnel_enabled(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": "5432",
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
        "ssh_tunnel_enabled": "True",
        "ssh_tunnel_host": "other-host.com",
        "ssh_tunnel_port": "55550",
        "ssh_tunnel_auth_type": "password",
        "ssh_tunnel_auth_type_username": "username",
        "ssh_tunnel_auth_type_password": "password",
    }

    activity_inputs = await _setup(team, job_inputs)

    def mock_get_tunnel(self_class, host, port):
        class MockedTunnel:
            local_bind_host: str = "other-host.com"
            local_bind_port: int = 55550

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, exc_traceback):
                pass

        return MockedTunnel()

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.sql_database.sql_source_for_type") as sql_source_for_type,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data._run"),
        mock.patch.object(SSHTunnel, "get_tunnel", mock_get_tunnel),
    ):
        await activity_environment.run(import_data_activity, activity_inputs)

        sql_source_for_type.assert_called_once_with(
            source_type=ExternalDataSource.Type.POSTGRES,
            host="other-host.com",
            port=55550,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            incremental_field=None,
            incremental_field_type=None,
            team_id=team.id,
        )
