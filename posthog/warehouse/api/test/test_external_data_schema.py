import uuid
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from django.conf import settings
from django.test.client import Client as HttpClient

import psycopg
import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.temporal.common.schedule import describe_schedule
from posthog.temporal.data_imports.sources.stripe.source import StripeSource
from posthog.warehouse.api.test.utils import create_external_data_source_ok
from posthog.warehouse.models import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.types import ExternalDataSourceType

pytestmark = [
    pytest.mark.django_db,
]


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
    def _setup(self, postgres_connection, postgres_config, temporal):
        self.postgres_connection = postgres_connection
        self.postgres_config = postgres_config
        self.temporal = temporal

    def test_incremental_fields_stripe(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        with mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )
        payload = response.json()

        assert payload == {
            "incremental_fields": [
                {"label": "created_at", "type": "datetime", "field": "created", "field_type": "integer"}
            ],
            "incremental_available": False,
            "append_available": True,
            "full_refresh_available": True,
        }

    def test_incremental_fields_missing_source_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="bad_source",
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        assert response.status_code == 400

    def test_incremental_fields_missing_table_name(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Some_other_non_existent_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )

        assert response.status_code == 400

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
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
        )
        payload = response.json()

        assert payload == {
            "incremental_fields": [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}],
            "incremental_available": True,
            "append_available": True,
            "full_refresh_available": True,
        }

    def test_update_schema_change_sync_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_time_of_day="12:00:00",
        )

        with mock.patch(
            "posthog.warehouse.api.external_data_schema.trigger_external_data_workflow"
        ) as mock_trigger_external_data_workflow:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()
            schema.refresh_from_db()
            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_change_sync_type_incremental_field(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "some_other_field", "incremental_field_type": "integer"},
            table=table,
        )

        with (
            mock.patch(
                "posthog.warehouse.api.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "field", "incremental_field_type": "integer"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()

            schema.refresh_from_db()

            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type_config.get("incremental_field") == "field"
            assert schema.sync_type_config.get("incremental_field_type") == "integer"
            assert schema.sync_type_config.get("incremental_field_last_value") == 1


class TestUpdateExternalDataSchema:
    @pytest.fixture
    def organization(self):
        organization = create_organization("Test Org")

        yield organization

        organization.delete()

    @pytest.fixture
    def team(self, organization):
        team = create_team(organization)

        yield team

        team.delete()

    @pytest.fixture
    def user(self, team):
        user = create_user("test@user.com", "Test User", team.organization)

        yield user

        user.delete()

    def test_update_schema_change_should_sync_on_without_existing_schedule(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=False).first()
        assert schema is not None

        # This is expected to raise an RPCError if the schedule doesn't exist yet
        with pytest.raises(RPCError):
            schedule_desc = describe_schedule(temporal, str(schema.id))

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

    def test_update_schema_change_should_sync_off(self, team, user, client: HttpClient, temporal):
        """Test that we can pause a schedule by setting should_sync to false.

        We try to simulate the behaviour in production as close as possible since the previous tests using mocks were
        not catching issues with us not updating the schedule in Temporal correctly.
        """
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=True).first()
        assert schema is not None

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            # here we try to mimic the payload from the frontend, which actually sends all fields, not just should_sync
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": False,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is False

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is True

    def test_update_schema_change_should_sync_on_with_existing_schedule(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=True).first()
        assert schema is not None

        # ensure schedule exists first
        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

        # pause the schedule
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": False,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is False

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is True

        # now turn it back on
        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        # needed to appease mypy ;-(
        new_schema = schema
        assert new_schema.should_sync is True

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.state.paused is False

    def test_update_schema_change_should_sync_on_without_sync_type(self, team, user, client: HttpClient, temporal):
        """Test that we can turn on a schema that doesn't have a sync type set.

        Not sure in which cases this can happen.
        """
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, should_sync=False).first()
        assert schema is not None
        schema.sync_type = None
        schema.save()

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": None,
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_schema_change_sync_type_with_invalid_type(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "blah",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "6hour",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_update_schema_sync_frequency(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "7day",
                "sync_time_of_day": "00:00:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=7)

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].every == timedelta(days=7)

    def test_update_schema_sync_time_of_day_when_previously_not_set(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, sync_time_of_day=None).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "24hour",
                "sync_time_of_day": "15:30:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_time_of_day is not None
        assert schema.sync_time_of_day.hour == 15
        assert schema.sync_time_of_day.minute == 30
        assert schema.sync_time_of_day.second == 0

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].offset == timedelta(hours=15, minutes=30)

    def test_update_schema_sync_time_of_day_when_previously_set(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source_id = create_external_data_source_ok(client, team.pk)
        schema = ExternalDataSchema.objects.filter(source_id=source_id, sync_time_of_day__isnull=False).first()
        assert schema is not None

        response = client.patch(
            f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
            data={
                "id": str(schema.id),
                "name": schema.name,
                "should_sync": True,
                "incremental": False,
                "status": "Completed",
                "sync_type": "full_refresh",
                "incremental_field": None,
                "incremental_field_type": None,
                "sync_frequency": "24hour",
                "sync_time_of_day": "15:30:00",
            },
            content_type="application/json",
        )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.sync_time_of_day is not None
        assert schema.sync_time_of_day.hour == 15
        assert schema.sync_time_of_day.minute == 30
        assert schema.sync_time_of_day.second == 0

        schedule_desc = describe_schedule(temporal, str(schema.id))
        assert schedule_desc.schedule.spec.intervals[0].offset == timedelta(hours=15, minutes=30)
