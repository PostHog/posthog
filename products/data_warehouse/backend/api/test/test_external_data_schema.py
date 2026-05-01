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
from parameterized import parameterized
from rest_framework import status
from temporalio.service import RPCError

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.api.test.test_user import create_user
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.temporal.common.schedule import describe_schedule
from posthog.temporal.data_imports.sources.common.base import WebhookCreationResult
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.stripe.source import StripeSource

from products.data_warehouse.backend.api.test.utils import create_external_data_source_ok
from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.external_data_source.webhooks import WebhookHogFunctionCreateResult
from products.data_warehouse.backend.models import DataWarehouseTable
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.types import ExternalDataSourceType

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
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
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
            "cdc_available": None,
            "full_refresh_available": True,
            "supports_webhooks": False,
            "available_columns": [],
            "detected_primary_keys": None,
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
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
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
            "incremental_fields": [
                {
                    "label": "id",
                    "type": "integer",
                    "field": "id",
                    "field_type": "integer",
                    "nullable": True,
                    # Table has no index on `id`, so the warning UI will fire for this field.
                    "is_indexed": False,
                }
            ],
            "incremental_available": True,
            "append_available": True,
            "cdc_available": None,
            "full_refresh_available": True,
            "supports_webhooks": False,
            "available_columns": [
                {"field": "id", "label": "id", "type": "integer", "nullable": True},
            ],
            "detected_primary_keys": ["id"],
        }

    def test_update_schema_change_sync_type(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
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

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()
            schema.refresh_from_db()
            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    @parameterized.expand(
        [ExternalDataSchema.SyncType.APPEND, ExternalDataSchema.SyncType.INCREMENTAL],
    )
    def test_update_schema_to_webhook_does_not_reset_pipeline(self, from_sync_type):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=from_sync_type,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "incremental_field_last_value": 1000,
            },
            table=table,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=True,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook"},
            )

            assert response.status_code == 200
            mock_trigger_external_data_workflow.assert_not_called()

            schema.refresh_from_db()

            assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK
            assert schema.sync_type_config.get("reset_pipeline") is None
            assert schema.sync_type_config.get("incremental_field") == "created"
            assert schema.sync_type_config.get("incremental_field_type") == "integer"
            assert schema.sync_type_config.get("incremental_field_last_value") == 1000

    def test_update_schema_change_sync_type_incremental_field(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
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
                "products.data_warehouse.backend.api.external_data_schema.trigger_external_data_workflow"
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

    def test_update_schema_with_primary_key_columns(self):
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
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={
                "sync_type": "incremental",
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id", "source_id"],
            },
        )

        assert response.status_code == 200

        schema.refresh_from_db()

        assert schema.sync_type_config.get("primary_key_columns") == ["_id", "source_id"]
        assert schema.primary_key_columns == ["_id", "source_id"]

    def test_update_schema_rejects_primary_key_change_with_existing_data(self):
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
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["id"],
            },
            table=table,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={
                "sync_type": "incremental",
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        assert response.status_code == 400

    def test_update_schema_primary_key_columns_not_reset_on_full_refresh(self):
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
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"sync_type": "full_refresh"},
        )

        assert response.status_code == 200

        schema.refresh_from_db()

        assert schema.sync_type_config.get("primary_key_columns") == ["_id"]

    def test_switch_synced_incremental_schema_to_append_with_existing_pk(self):
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
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["id"],
            },
            table=table,
        )

        with mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "append",
                    "incremental_field": "created",
                    "incremental_field_type": "integer",
                    "primary_key_columns": None,
                },
            )

            assert response.status_code == 200

            schema.refresh_from_db()
            assert schema.sync_type == ExternalDataSchema.SyncType.APPEND
            assert schema.sync_type_config.get("primary_key_columns") is None

    def test_primary_key_columns_returned_in_serializer(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "created",
                "incremental_field_type": "integer",
                "primary_key_columns": ["_id"],
            },
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/",
        )

        assert response.status_code == 200
        assert response.json()["results"][0]["primary_key_columns"] == ["_id"]

    def test_update_schema_to_webhook_triggers_webhook_creation(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_hog_function = mock.MagicMock()
        mock_hog_function.id = uuid.uuid4()
        mock_hog_function.inputs = {"schema_mapping": {"value": {}}, "source_id": {"value": "test-source-id"}}
        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function=mock_hog_function,
            webhook_url="https://test.com/webhook",
            hog_function_created=True,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ) as mock_get_or_create,
            mock.patch.object(
                StripeSource, "create_webhook", return_value=WebhookCreationResult(success=True)
            ) as mock_create_webhook,
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_called_once()
        mock_create_webhook.assert_called_once()

    def test_update_schema_to_incremental_does_not_trigger_webhook(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_full_refresh_does_not_trigger_webhook(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_webhook_non_webhook_source_no_webhook_result(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "test",
                "user": "user",
                "password": "pass",
                "schema": "public",
                "ssh_tunnel_enabled": False,
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "id", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()

    def test_update_schema_to_webhook_non_webhook_schema_no_webhook_result(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="CustomerBalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_non_webhook_schemas = [
            SourceSchema(
                name="CustomerBalanceTransaction",
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=False,
            ),
        ]

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_non_webhook_schemas),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.get_or_create_webhook_hog_function"
            ) as mock_get_or_create,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        mock_get_or_create.assert_not_called()


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

    def test_update_schema_exposes_direct_postgres_table_without_sync_type(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=False,
            sync_type=None,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.sync_external_data_job_workflow"
            ) as mock_sync_external_data_job_workflow,
        ):
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

            assert response.status_code == 200
            schema.refresh_from_db()
            assert schema.should_sync is True
            assert schema.table is not None
            assert schema.table.deleted is False
            assert schema.table.url_pattern == DIRECT_POSTGRES_URL_PATTERN
            mock_external_data_workflow_exists.assert_not_called()
            mock_sync_external_data_job_workflow.assert_not_called()

    def test_update_schema_hides_direct_postgres_table_when_disabled(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with mock.patch("products.data_warehouse.backend.api.external_data_schema.Database.create_for"):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": False,
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

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True

    def test_update_schema_cdc_with_blank_source_schema_uses_physical_schema_metadata(
        self, team, user, client: HttpClient, temporal
    ):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "schema": "",
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            },
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="analytics.events",
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                    "source_schema": "analytics",
                    "source_table_name": "events",
                }
            },
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.ExternalDataSchemaSerializer._alter_cdc_publication"
            ) as mock_alter_cdc_publication,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch("products.data_warehouse.backend.api.external_data_schema.sync_external_data_job_workflow"),
            mock.patch("products.data_warehouse.backend.api.external_data_schema.sync_cdc_extraction_schedule"),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={
                    "id": str(schema.id),
                    "name": schema.name,
                    "should_sync": True,
                    "incremental": False,
                    "status": "Completed",
                    "sync_type": "cdc",
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "sync_frequency": "6hour",
                    "sync_time_of_day": "00:00:00",
                },
                content_type="application/json",
            )

        assert response.status_code == 200
        mock_alter_cdc_publication.assert_called_once()
        assert mock_alter_cdc_publication.call_args.args == (
            source,
            "test_pub",
            "analytics",
            "events",
        )

    def test_delete_data_hides_direct_postgres_table(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.POSTGRES,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={},
        )
        table = DataWarehouseTable.objects.create(
            name="accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="accounts",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        response = client.delete(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/delete_data")

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.should_sync is False
        assert schema.table_id == table.id
        assert DataWarehouseTable.raw_objects.get(pk=table.pk).deleted is True

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

    def test_update_webhook_schema_reenable_triggers_reset_pipeline(self, team, user, client: HttpClient, temporal):
        source = ExternalDataSource.objects.create(
            team=team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        client.force_login(user)

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.sync_external_data_job_workflow",
            ),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    def test_update_webhook_schema_reenable_skips_reset_if_never_synced(self, team, user, client: HttpClient, temporal):
        source = ExternalDataSource.objects.create(
            team=team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=False,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

        client.force_login(user)

        with (
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.data_warehouse.backend.api.external_data_schema.sync_external_data_job_workflow",
            ),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200

        schema.refresh_from_db()
        assert schema.should_sync is True
        assert schema.sync_type_config.get("reset_pipeline") is None
        mock_trigger.assert_not_called()


class TestCancelExternalDataSchema(APIBaseTest):
    @mock.patch("products.data_warehouse.backend.api.external_data_schema.cancel_external_data_workflow")
    def test_cancel_running_sync(self, mock_cancel):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "123"}
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.RUNNING,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        from products.data_warehouse.backend.models.external_data_job import ExternalDataJob

        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="test-workflow-id",
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 200
        mock_cancel.assert_called_once_with(job.workflow_id)

    @mock.patch("products.data_warehouse.backend.api.external_data_schema.cancel_external_data_workflow")
    def test_cancel_when_no_running_job(self, mock_cancel):
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

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/cancel/",
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "No running sync to cancel."
        mock_cancel.assert_not_called()


class TestExternalDataSchemaAPIKeyScopes(APIBaseTest):
    def _make_api_key(self, scopes: list[str]) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.user,
            label="test",
            secure_value=hash_key_value(value),
            scopes=scopes,
        )
        return value

    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"stripe_secret_key": "123"},
        )
        self.schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )
        self.client.force_authenticate(None)

    @parameterized.expand(
        [
            ("external_data_source:read", "GET", "list", True),
            ("external_data_source:read", "GET", "retrieve", True),
            ("external_data_source:read", "PATCH", "partial_update", False),
            ("external_data_source:write", "GET", "list", True),
            ("external_data_source:write", "PATCH", "partial_update", True),
            ("other_scope:read", "GET", "list", False),
            ("other_scope:write", "PATCH", "partial_update", False),
        ]
    )
    def test_api_key_scope_gating(self, scope, method, action, should_have_access):
        api_key = self._make_api_key([scope])
        headers = {"authorization": f"Bearer {api_key}"}

        if action == "list":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/"
            response = self.client.get(url, headers=headers)
        elif action == "retrieve":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/"
            response = self.client.get(url, headers=headers)
        elif action == "partial_update":
            url = f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/"
            response = self.client.patch(url, {"should_sync": False}, format="json", headers=headers)
        else:
            self.fail(f"Unknown action: {action}")

        if should_have_access:
            self.assertNotEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected access but got 403 for {scope} on {method} {action}",
            )
        else:
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected 403 but got {response.status_code} for {scope} on {method} {action}",
            )


class TestExternalDataSchemaSerializerValidation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"stripe_secret_key": "123"},
        )
        self.schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={"incremental_field": "created", "incremental_field_type": "integer"},
        )

    def test_update_sync_type_null_clears_existing_value(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"sync_type": None},
            format="json",
        )
        assert response.status_code == 200
        self.schema.refresh_from_db()
        assert self.schema.sync_type is None

    def test_update_absent_sync_type_preserves_existing_value(self):
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{self.schema.id}/",
            {"should_sync": True},
            format="json",
        )
        assert response.status_code == 200
        self.schema.refresh_from_db()
        assert self.schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
