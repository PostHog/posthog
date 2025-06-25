from typing import Any
from unittest import mock

import pytest

from posthog.models.team.team import Team
from posthog.temporal.data_imports.settings import import_data_activity_sync
from posthog.temporal.data_imports.workflow_activities.import_data_sync import ImportDataActivityInputs
from posthog.warehouse.models.credential import DataWarehouseCredential
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.ssh_tunnel import SSHTunnel
from posthog.warehouse.models.table import DataWarehouseTable


def _setup(team: Team, job_inputs: dict[Any, Any]) -> ImportDataActivityInputs:
    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSource.Type.POSTGRES,
        job_inputs=job_inputs,
    )
    credentials = DataWarehouseCredential.objects.create(access_key="blah", access_secret="blah", team=team)
    warehouse_table = DataWarehouseTable.objects.create(
        name="table_1",
        format="Parquet",
        team=team,
        external_data_source=source,
        external_data_source_id=source.id,
        credential=credentials,
        url_pattern="https://bucket.s3/data/*",
        columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name="table_1",
        source=source,
        table=warehouse_table,
        should_sync=True,
        status=ExternalDataSchema.Status.COMPLETED,
        last_synced_at="2024-01-01",
    )
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id="some_workflow_id",
        pipeline_version=ExternalDataJob.PipelineVersion.V1,
    )

    return ImportDataActivityInputs(team_id=team.pk, schema_id=schema.pk, source_id=source.pk, run_id=str(job.pk))


@pytest.mark.django_db(transaction=True)
def test_job_inputs_with_whitespace(activity_environment, team, **kwargs):
    job_inputs = {
        "host": " host.com   ",
        "port": 5432,
        "user": "Username   ",
        "password": "   password",
        "database": "  database",
        "schema": "schema       ",
    }

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.postgres.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            host="host.com",
            port=5432,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            db_incremental_field_last_value=None,
            incremental_field=None,
            incremental_field_type=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
def test_postgres_source_without_ssh_tunnel(activity_environment, team, **kwargs):
    job_inputs = {
        "host": "host.com",
        "port": 5432,
        "user": "Username",
        "password": "password",
        "database": "database",
        "schema": "schema",
    }

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.postgres.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            host="host.com",
            port=5432,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
def test_postgres_source_with_ssh_tunnel_disabled(activity_environment, team, **kwargs):
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

    activity_inputs = _setup(team, job_inputs)

    with (
        mock.patch("posthog.temporal.data_imports.pipelines.postgres.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            host="host.com",
            port=5432,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            team_id=team.id,
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
def test_postgres_source_with_ssh_tunnel_enabled(activity_environment, team, **kwargs):
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

    activity_inputs = _setup(team, job_inputs)

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
        mock.patch("posthog.temporal.data_imports.pipelines.postgres.postgres_source") as mock_postgres_source,
        mock.patch("posthog.temporal.data_imports.workflow_activities.import_data_sync._run"),
        mock.patch.object(SSHTunnel, "get_tunnel", mock_get_tunnel),
    ):
        activity_environment.run(import_data_activity_sync, activity_inputs)

        mock_postgres_source.assert_called_once_with(
            host="other-host.com",
            port=55550,
            user="Username",
            password="password",
            database="database",
            sslmode="prefer",
            schema="schema",
            table_names=["table_1"],
            should_use_incremental_field=False,
            logger=mock.ANY,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            team_id=team.id,
        )
