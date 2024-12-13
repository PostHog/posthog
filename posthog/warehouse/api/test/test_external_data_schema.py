from datetime import timedelta
from unittest import mock
import uuid
import psycopg
import pytest
from asgiref.sync import sync_to_async
import pytest_asyncio
from posthog.test.base import APIBaseTest
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from django.conf import settings


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
    if setup_postgres_test_db:
        await anext(setup_postgres_test_db)

    connection = await psycopg.AsyncConnection.connect(
        user=postgres_config["user"],
        password=postgres_config["password"],
        dbname=postgres_config["database"],
        host=postgres_config["host"],
        port=postgres_config["port"],
    )

    yield connection

    await connection.close()


@pytest.mark.usefixtures("postgres_connection", "postgres_config")
class TestExternalDataSchema(APIBaseTest):
    @pytest.fixture(autouse=True)
    def _setup(self, postgres_connection, postgres_config):
        self.postgres_connection = postgres_connection
        self.postgres_config = postgres_config

    def test_incremental_fields_stripe(self):
        soruce = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSource.Type.STRIPE,
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=soruce,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )
        payload = response.json()

        assert payload == [{"label": "created_at", "type": "datetime", "field": "created", "field_type": "integer"}]

    def test_incremental_fields_missing_source_type(self):
        soruce = ExternalDataSource.objects.create(
            team=self.team,
            source_type="bad_source",
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=soruce,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        assert response.status_code == 400

    def test_incremental_fields_missing_table_name(self):
        soruce = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSource.Type.STRIPE,
        )
        schema = ExternalDataSchema.objects.create(
            name="Some_other_non_existent_table",
            team=self.team,
            source=soruce,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        # should respond but with empty list. Example: Hubspot has not incremental fields but the response should be an empty list so that full refresh is selectable
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.asyncio
    async def test_incremental_fields_postgres(self):
        if not isinstance(self.postgres_connection, psycopg.AsyncConnection):
            postgres_connection: psycopg.AsyncConnection = await anext(self.postgres_connection)
        else:
            postgres_connection = self.postgres_connection

        await postgres_connection.execute(
            "CREATE TABLE IF NOT EXISTS {schema}.posthog_test (id integer)".format(
                schema=self.postgres_config["schema"]
            )
        )
        await postgres_connection.execute(
            "INSERT INTO {schema}.posthog_test (id) VALUES (1)".format(schema=self.postgres_config["schema"])
        )
        await postgres_connection.commit()

        source = await sync_to_async(ExternalDataSource.objects.create)(
            source_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            destination_id=uuid.uuid4(),
            team=self.team,
            status="running",
            source_type="Postgres",
            job_inputs={
                "host": self.postgres_config["host"],
                "port": self.postgres_config["port"],
                "database": self.postgres_config["database"],
                "user": self.postgres_config["user"],
                "password": self.postgres_config["password"],
                "schema": self.postgres_config["schema"],
                "ssh_tunnel_enabled": False,
            },
        )

        schema = await sync_to_async(ExternalDataSchema.objects.create)(
            name="posthog_test",
            team=self.team,
            source=source,
        )

        response = await sync_to_async(self.client.post)(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )
        payload = response.json()

        assert payload == [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}]

    def test_update_schema_change_sync_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with mock.patch(
            "posthog.warehouse.api.external_data_schema.trigger_external_data_workflow"
        ) as mock_trigger_external_data_workflow:
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_called_once()
            source.refresh_from_db()
            assert source.job_inputs.get("reset_pipeline") == "True"

    def test_update_schema_change_sync_type_incremental_field(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "some_other_field", "incremental_field_type": "datetime"},
        )

        with mock.patch(
            "posthog.warehouse.api.external_data_schema.trigger_external_data_workflow"
        ) as mock_trigger_external_data_workflow:
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "field", "incremental_field_type": "integer"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_called_once()

            source.refresh_from_db()
            assert source.job_inputs.get("reset_pipeline") == "True"

            schema.refresh_from_db()
            assert schema.sync_type_config.get("incremental_field") == "field"
            assert schema.sync_type_config.get("incremental_field_type") == "integer"

    def test_update_schema_change_should_sync_off(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "posthog.warehouse.api.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "posthog.warehouse.api.external_data_schema.pause_external_data_schedule"
            ) as mock_pause_external_data_schedule,
        ):
            mock_external_data_workflow_exists.return_value = True

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": False},
            )

            assert response.status_code == 200
            mock_pause_external_data_schedule.assert_called_once()

            schema.refresh_from_db()
            assert schema.should_sync is False

    def test_update_schema_change_should_sync_on_with_existing_schedule(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "posthog.warehouse.api.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "posthog.warehouse.api.external_data_schema.unpause_external_data_schedule"
            ) as mock_unpause_external_data_schedule,
        ):
            mock_external_data_workflow_exists.return_value = True

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
            )

            assert response.status_code == 200
            mock_unpause_external_data_schedule.assert_called_once()

            schema.refresh_from_db()
            assert schema.should_sync is True

    def test_update_schema_change_should_sync_on_without_existing_schedule(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "posthog.warehouse.api.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "posthog.warehouse.api.external_data_schema.sync_external_data_job_workflow"
            ) as mock_sync_external_data_job_workflow,
        ):
            mock_external_data_workflow_exists.return_value = False

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
            )

            assert response.status_code == 200
            mock_sync_external_data_job_workflow.assert_called_once()

            schema.refresh_from_db()
            assert schema.should_sync is True

    def test_update_schema_change_should_sync_on_without_sync_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=None,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"should_sync": True},
        )

        assert response.status_code == 400

    def test_update_schema_change_sync_type_with_invalid_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=None,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "blah"},
        )

        assert response.status_code == 400

    def test_update_schema_sync_frequency(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSource.Type.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_frequency_interval=timedelta(hours=24),
        )

        with (
            mock.patch(
                "posthog.warehouse.api.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "posthog.warehouse.api.external_data_schema.sync_external_data_job_workflow"
            ) as mock_sync_external_data_job_workflow,
        ):
            mock_external_data_workflow_exists.return_value = True

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "7day"},
            )

            assert response.status_code == 200
            mock_sync_external_data_job_workflow.assert_called_once()

            schema.refresh_from_db()
            assert schema.sync_frequency_interval == timedelta(days=7)
