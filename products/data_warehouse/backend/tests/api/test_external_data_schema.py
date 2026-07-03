import uuid
from datetime import timedelta
from typing import Any

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
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import generate_random_token_personal
from posthog.temporal.common.schedule import describe_schedule

from products.data_modeling.backend.facade.models import Edge, Node
from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.direct_snowflake import DIRECT_SNOWFLAKE_URL_PATTERN
from products.data_warehouse.backend.logic.external_data_source.webhooks import WebhookHogFunctionCreateResult
from products.data_warehouse.backend.tests.api.utils import create_external_data_source_ok
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    WebhookCreationResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource

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
            "xmin_available": None,
            "full_refresh_available": True,
            "supports_webhooks": True,
            "webhook_only": False,
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
                },
                # xmin is synthetic: advertised for any ordinary PG13+ table, unindexed by definition.
                {
                    "label": "xmin",
                    "type": "xid",
                    "field": "xmin",
                    "field_type": "xid",
                    "is_indexed": False,
                },
            ],
            "incremental_available": True,
            "append_available": True,
            "cdc_available": None,
            "xmin_available": None,
            "full_refresh_available": True,
            "supports_webhooks": False,
            "webhook_only": False,
            "available_columns": [
                {"field": "id", "label": "id", "type": "integer", "nullable": True},
            ],
            "detected_primary_keys": ["id"],
        }

    @parameterized.expand(
        [
            # (test name, source_cdc_enabled, team_ff_enabled, expected_cdc_available)
            ("source_enabled_team_enabled", True, True, True),
            ("source_enabled_team_disabled", True, False, None),
            ("source_disabled_team_enabled", False, True, None),
            ("source_disabled_team_disabled", False, False, None),
        ]
    )
    def test_incremental_fields_cdc_available_gating(
        self, _name: str, source_cdc_enabled: bool, team_ff_enabled: bool, expected_cdc_available
    ):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        job_inputs = {
            "host": "localhost",
            "port": 5432,
            "database": "postgres",
            "user": "postgres",
            "password": "postgres",
            "schema": "public",
            "ssh_tunnel_enabled": False,
        }
        if source_cdc_enabled:
            job_inputs["cdc_enabled"] = True

        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type="Postgres",
            job_inputs=job_inputs,
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        fake_schema = SourceSchema(
            name="some_table",
            supports_incremental=False,
            supports_append=False,
            supports_cdc=True,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )

        with (
            mock.patch.object(PostgresSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(PostgresSource, "get_schemas", return_value=[fake_schema]),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
                return_value=team_ff_enabled,
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["cdc_available"] is expected_cdc_available

    @parameterized.expand(
        [
            # (test name, source_type, supports_xmin, expected_xmin_available)
            ("postgres_capable", ExternalDataSourceType.POSTGRES, True, True),
            ("postgres_not_capable", ExternalDataSourceType.POSTGRES, False, False),
            ("non_postgres_capable", ExternalDataSourceType.MYSQL, True, None),
        ]
    )
    def test_incremental_fields_xmin_available_gating(
        self, _name: str, source_type, supports_xmin: bool, expected_xmin_available
    ):
        # xmin is Postgres-only: the endpoint must report `xmin_available=None` for any other source,
        # even one that erroneously sets `supports_xmin=True`.
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        source_impl = PostgresSource if source_type == ExternalDataSourceType.POSTGRES else MySQLSource
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="some_table",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        fake_schema = SourceSchema(
            name="some_table",
            supports_incremental=False,
            supports_append=False,
            supports_xmin=supports_xmin,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )

        with (
            mock.patch.object(source_impl, "validate_credentials", return_value=(True, None)),
            mock.patch.object(source_impl, "get_schemas", return_value=[fake_schema]),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_xmin_enabled_for_team",
                return_value=True,
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["xmin_available"] is expected_xmin_available

    def test_incremental_fields_matches_schema_by_name(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="C123",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        )

        # Mimics sources (e.g. Slack) that ignore `names` and return every schema. The first
        # element is an unrelated table; the endpoint must pick the one matching instance.name.
        all_schemas = [
            SourceSchema(name="$channels", supports_incremental=False, supports_append=False, supports_webhooks=False),
            SourceSchema(name="C123", supports_incremental=False, supports_append=False, supports_webhooks=True),
        ]

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=all_schemas),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["supports_webhooks"] is True

    def test_incremental_fields_returns_400_when_schema_name_absent(self):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type=ExternalDataSourceType.STRIPE, job_inputs={"stripe_secret_key": "test_key"}
        )
        schema = ExternalDataSchema.objects.create(
            name="C999",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        )

        other_schemas = [
            SourceSchema(name="$channels", supports_incremental=False, supports_append=False, supports_webhooks=False),
        ]

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=other_schemas),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/incremental_fields",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

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
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
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

    def test_update_schema_sync_type_is_logged_to_activity(self):
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
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )
            assert response.status_code == 200

        logs = ActivityLog.objects.filter(scope="ExternalDataSchema", item_id=str(schema.id), activity="updated")
        sync_type_changes = [
            c for log in logs for c in (log.detail or {}).get("changes", []) if c["field"] == "sync_type"
        ]
        assert sync_type_changes == [
            {
                "type": "ExternalDataSchema",
                "field": "sync_type",
                "action": "changed",
                "before": "incremental",
                "after": "full_refresh",
            }
        ]

    def test_update_schema_sets_and_clears_incremental_field_lookback_seconds(self):
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
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": 3600,
                },
            )
            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field_lookback_seconds"] == 3600
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field_lookback_seconds"] == 3600

            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": None,
                },
            )
            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field_lookback_seconds"] is None
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field_lookback_seconds"] is None

    def test_update_incremental_field_without_sync_type_persists(self):
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
            sync_type_config={
                "incremental_field": "created_at",
                "incremental_field_type": "timestamp",
                "incremental_field_last_value": "2026-06-14T15:33:31.802833",
            },
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            # A bare incremental_field edit — no sync_type re-sent — must actually persist, not just
            # echo the submitted value back in the response.
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"incremental_field": "updated_at"},
            )

            assert response.status_code == 200, response.json()
            assert response.json()["incremental_field"] == "updated_at"
            schema.refresh_from_db()
            assert schema.sync_type_config["incremental_field"] == "updated_at"

    def test_update_incremental_field_on_non_incremental_schema_errors(self):
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
            # Seed leftover config so the post-request assertion catches a regression that writes the
            # value rather than leaving it untouched (a missing key would pass trivially).
            sync_type_config={"incremental_field": "old_value", "primary_key_columns": ["id"]},
        )

        # Setting incremental_field on a full_refresh schema without switching sync_type can't be
        # applied — it must fail loudly instead of returning 200 and dropping the change.
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"incremental_field": "updated_at"},
        )

        assert response.status_code == 400, response.json()
        schema.refresh_from_db()
        assert schema.sync_type_config.get("incremental_field") == "old_value"

        # primary_key_columns is dropped the same way on a non-incremental schema, so it errors too.
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"primary_key_columns": ["other_id"]},
        )

        assert response.status_code == 400, response.json()
        schema.refresh_from_db()
        assert schema.sync_type_config.get("primary_key_columns") == ["id"]

    def test_incremental_field_lookback_seconds_survives_reset(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="BalanceTransaction",
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            sync_type_config={
                "incremental_field": "updated_at",
                "incremental_field_type": "timestamp",
                "incremental_field_last_value": "2026-06-14T15:33:31.802833",
                "incremental_field_lookback_seconds": 7200,
            },
        )

        schema.update_sync_type_config_for_reset_pipeline()

        schema.refresh_from_db()
        assert "incremental_field_last_value" not in schema.sync_type_config
        assert schema.sync_type_config["incremental_field_lookback_seconds"] == 7200

    def test_create_source_persists_lookback_for_incremental_omits_for_non_incremental(self):
        incremental_schema = SourceSchema(
            name="Orders",
            supports_incremental=True,
            supports_append=False,
            supports_webhooks=False,
        )
        full_refresh_schema = SourceSchema(
            name="Products",
            supports_incremental=False,
            supports_append=False,
            supports_webhooks=False,
        )

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=[incremental_schema, full_refresh_schema]),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "Stripe",
                    "payload": {
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                        "schemas": [
                            {
                                "name": "Orders",
                                "should_sync": True,
                                "sync_type": "incremental",
                                "incremental_field": "updated_at",
                                "incremental_field_type": "timestamp",
                                "incremental_field_lookback_seconds": 3600,
                            },
                            {
                                "name": "Products",
                                "should_sync": True,
                                "sync_type": "full_refresh",
                                "incremental_field_lookback_seconds": 3600,
                            },
                        ],
                    },
                },
                content_type="application/json",
            )

        assert response.status_code == 201, response.json()

        incremental = ExternalDataSchema.objects.get(
            source__team=self.team, name="Orders", sync_type=ExternalDataSchema.SyncType.INCREMENTAL
        )
        assert incremental.sync_type_config["incremental_field_lookback_seconds"] == 3600

        full_refresh = ExternalDataSchema.objects.get(
            source__team=self.team, name="Products", sync_type=ExternalDataSchema.SyncType.FULL_REFRESH
        )
        assert "incremental_field_lookback_seconds" not in full_refresh.sync_type_config

    def test_update_schema_rejects_lookback_above_60_days(self):
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
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={
                    "sync_type": "incremental",
                    "incremental_field": "updated_at",
                    "incremental_field_type": "timestamp",
                    "incremental_field_lookback_seconds": 5_184_001,  # 60 days + 1 second
                },
            )

        assert response.status_code == 400

    def test_create_source_rejects_lookback_above_60_days(self):
        incremental_schema = SourceSchema(
            name="Orders",
            supports_incremental=True,
            supports_append=False,
            supports_webhooks=False,
        )

        with (
            mock.patch.object(StripeSource, "validate_credentials", return_value=(True, None)),
            mock.patch.object(StripeSource, "get_schemas", return_value=[incremental_schema]),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "Stripe",
                    "payload": {
                        "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                        "schemas": [
                            {
                                "name": "Orders",
                                "should_sync": True,
                                "sync_type": "incremental",
                                "incremental_field": "updated_at",
                                "incremental_field_type": "timestamp",
                                "incremental_field_lookback_seconds": 5_184_001,  # 60 days + 1 second
                            },
                        ],
                    },
                },
                content_type="application/json",
            )

        assert response.status_code == 400
        assert "5184000" in response.json().get("message", "")
        assert not ExternalDataSource.objects.filter(team=self.team, source_type="Stripe").exists()

    @parameterized.expand(
        [
            # Stored PK from earlier discovery — reuse it; no caller override needed.
            (
                "reuses_stored_primary_key",
                {"primary_key_columns": ["id"], "schema_metadata": {}},
                None,
                status.HTTP_200_OK,
                ExternalDataSchema.SyncType.CDC,
                ["id"],
            ),
            # Caller explicitly provides PK — takes precedence over (and persists alongside)
            # whatever was stored.
            (
                "caller_override_wins",
                {"primary_key_columns": ["old"], "schema_metadata": {}},
                ["new_pk"],
                status.HTTP_200_OK,
                ExternalDataSchema.SyncType.CDC,
                ["new_pk"],
            ),
            # No stored PK, no override → refuse the switch.
            (
                "rejects_when_no_primary_key_available",
                {"schema_metadata": {}},
                None,
                status.HTTP_400_BAD_REQUEST,
                ExternalDataSchema.SyncType.FULL_REFRESH,
                None,
            ),
        ]
    )
    def test_update_schema_to_cdc(
        self,
        _name: str,
        initial_sync_type_config: dict,
        payload_pk: list[str] | None,
        expected_status: int,
        expected_sync_type: str,
        expected_pk_columns: list[str] | None,
    ):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="quotes",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config=initial_sync_type_config,
        )

        request_body: dict[str, Any] = {"sync_type": "cdc"}
        if payload_pk is not None:
            request_body["primary_key_columns"] = payload_pk

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data=request_body,
            )

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_400_BAD_REQUEST:
            assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == expected_sync_type
        if expected_pk_columns is not None:
            assert schema.sync_type_config["primary_key_columns"] == expected_pk_columns
            assert schema.sync_type_config["cdc_mode"] == "snapshot"

    def test_update_cdc_schema_rejects_primary_key_change_with_existing_data(self):
        # CDC uses the PK as the UPDATE/DELETE merge key, so — same as incremental — it can't be
        # changed once data has synced (the schema has a materialized table).
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "primary_key_columns": ["id"]},
            table=table,
        )

        with mock.patch(
            "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "cdc", "primary_key_columns": ["order_key"]},
            )

        assert response.status_code == 400
        assert "primary key cannot be changed" in str(response.json()).lower()

        schema.refresh_from_db()
        assert schema.sync_type_config["primary_key_columns"] == ["id"]

    def _xmin_postgres_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )

    @staticmethod
    def _xmin_discovery_patches(supports_xmin: bool = True, flag_enabled: bool = True):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

        fake_schema = SourceSchema(
            name="public.orders",
            supports_incremental=False,
            supports_append=False,
            supports_xmin=supports_xmin,
            incremental_fields=[],
            columns=[("id", "integer", False)],
            detected_primary_keys=["id"],
        )
        return (
            mock.patch.object(PostgresSource, "get_schemas", return_value=[fake_schema]),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_xmin_enabled_for_team",
                return_value=flag_enabled,
            ),
        )

    def test_update_schema_to_xmin_succeeds_with_primary_key(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={},
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches()
        with get_schemas_patch, flag_patch:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.XMIN
        assert schema.sync_type_config["primary_key_columns"] == ["id"]
        # xmin never sets CDC state.
        assert "cdc_mode" not in schema.sync_type_config

    def test_update_schema_to_xmin_rejected_without_primary_key(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={},
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches()
        with get_schemas_patch, flag_patch:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin"},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_to_xmin_rejected_for_non_postgres(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.MYSQL,
            job_inputs={"host": "h", "port": 3306, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        with mock.patch(
            "products.data_warehouse.backend.presentation.views.external_data_schema.is_xmin_enabled_for_team",
            return_value=True,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "postgres" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_to_xmin_rejected_when_table_not_capable(self):
        # A plain view / partitioned parent reports supports_xmin=False — reject even with a PK.
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches(supports_xmin=False)
        with get_schemas_patch, flag_patch:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not available" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_to_xmin_rejected_when_flag_disabled(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches(flag_enabled=False)
        with get_schemas_patch, flag_patch:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not enabled" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_xmin_accepts_row_filters(self):
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={
                "primary_key_columns": ["id"],
                "schema_metadata": {"columns": [{"name": "id", "data_type": "integer", "is_nullable": False}]},
            },
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches()
        with get_schemas_patch, flag_patch:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"row_filters": [{"column": "id", "operator": ">", "value": "5"}]},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.row_filters == [{"column": "id", "operator": ">", "value": "5"}]

    @parameterized.expand(
        [
            ("one_minute_rejected", "1min", 400),
            ("five_minute_accepted", "5min", 200),
        ]
    )
    def test_update_schema_xmin_floors_at_five_minutes(self, _name, sync_frequency, expected_status):
        # xmin does not get CDC's 1-minute cadence — it floors at the normal 5-minute incremental cadence.
        source = self._xmin_postgres_source()
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={"primary_key_columns": ["id"]},
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches()
        with (
            get_schemas_patch,
            flag_patch,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"], "sync_frequency": sync_frequency},
            )

        assert response.status_code == expected_status, response.content
        if expected_status == 400:
            assert "1-minute" in str(response.json()).lower() or "cdc" in str(response.json()).lower()

    def test_update_schema_to_xmin_forces_full_resync(self):
        # Switching to xmin from another strategy adds the `_ph_xmin` control column to the physical
        # schema, so the existing Delta table must be rebuilt — force a full resync.
        source = self._xmin_postgres_source()
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_type_config={"primary_key_columns": ["id"]},
            table=table,
        )

        get_schemas_patch, flag_patch = self._xmin_discovery_patches()
        with (
            get_schemas_patch,
            flag_patch,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "xmin", "primary_key_columns": ["id"]},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.XMIN
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    def test_update_schema_from_xmin_forces_full_resync(self):
        # Leaving xmin for another strategy must also rebuild the table — the lingering `_ph_xmin`
        # column would otherwise break the incremental write.
        source = self._xmin_postgres_source()
        table = DataWarehouseTable.objects.create(team=self.team)
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.XMIN,
            sync_type_config={"primary_key_columns": ["id"], "xmin_last_value": 123},
            table=table,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger,
            mock.patch.object(DataWarehouseTable, "get_max_value_for_column", return_value=1),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "incremental", "incremental_field": "id", "incremental_field_type": "integer"},
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        assert schema.sync_type_config.get("reset_pipeline") is True
        mock_trigger.assert_called_once()

    @parameterized.expand(
        [
            ("incremental", ExternalDataSchema.SyncType.INCREMENTAL, 400),
            ("full_refresh", ExternalDataSchema.SyncType.FULL_REFRESH, 400),
            ("cdc", ExternalDataSchema.SyncType.CDC, 200),
        ]
    )
    def test_update_schema_one_minute_frequency_only_for_cdc(self, _name, sync_type, expected_status):
        # A 1-minute cadence is CDC-only. The backend must enforce this regardless of caller
        # (UI, API, or MCP) so non-CDC schemas can't be pushed below the 5-minute floor.
        is_cdc = sync_type == ExternalDataSchema.SyncType.CDC
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES if is_cdc else ExternalDataSourceType.STRIPE,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=sync_type,
            sync_type_config={"primary_key_columns": ["id"]} if is_cdc else {},
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_cdc_extraction_schedule"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "1min"},
            )

        assert response.status_code == expected_status, response.content
        if expected_status == 400:
            assert "cdc" in str(response.json()).lower()
            schema.refresh_from_db()
            # Rejected before the interval is persisted.
            assert schema.sync_frequency_interval != timedelta(minutes=1)

    def test_update_schema_one_minute_clamps_on_switch_away_from_cdc(self):
        # A CDC schema on a 1-minute schedule switched to a non-CDC sync type without re-sending
        # sync_frequency would otherwise dead-end (1-minute is CDC-only). Instead of rejecting the
        # switch, clamp the inherited cadence to the non-CDC floor so the switch goes through.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"primary_key_columns": ["id"]},
            sync_frequency_interval=timedelta(minutes=1),
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_cdc_extraction_schedule"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "full_refresh"},
            )

        assert response.status_code == 200, response.content
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(minutes=5)
        assert schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH

    def test_update_schema_frequency_on_disabled_schema_does_not_touch_missing_schedule(self):
        # A disabled / never-activated schema has no Temporal schedule. Changing its sync frequency
        # must not try to update a schedule that doesn't exist (which raises "workflow not found");
        # the new frequency is just saved, to apply if/when the schema is enabled.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_frequency_interval=timedelta(hours=6),
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ) as mock_sync_workflow,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "30day"},
            )

        assert response.status_code == 200, response.content
        # The frequency is saved...
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=30)
        # ...but no schedule create/update is attempted, because the schema has no schedule to touch.
        mock_sync_workflow.assert_not_called()

    def test_update_schema_frequency_on_enabled_schema_without_schedule_creates_it(self):
        # An enabled schema whose Temporal schedule is missing should have it created when the
        # cadence is edited (even when should_sync isn't re-sent), not left silently unscheduled.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            sync_frequency_interval=timedelta(hours=6),
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ) as mock_sync_workflow,
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_frequency": "30day"},
            )

        assert response.status_code == 200, response.content
        schema.refresh_from_db()
        assert schema.sync_frequency_interval == timedelta(days=30)
        # The missing schedule is created (recovered) with the new cadence, not left absent.
        mock_sync_workflow.assert_called_once()
        assert mock_sync_workflow.call_args.kwargs["create"] is True

    def test_update_schema_enable_should_sync_rejects_cdc_without_primary_key(self):
        # Schemas already in CDC mode with an empty primary_key_columns (created before the
        # API gate landed) must not be re-enabled until a PK is added on the source side.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": 5432, "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="tracking_link",
            team=self.team,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "snapshot", "primary_key_columns": []},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"should_sync": True},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary key" in str(response.json()).lower()
        schema.refresh_from_db()
        assert schema.should_sync is False

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

        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function=mock.MagicMock(),
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
            ) as mock_trigger_external_data_workflow,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=True,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow"
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
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

    def test_update_schema_to_webhook_existing_function_reconciles_events(self):
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
        # hog_function_created=False → existing webhook, so the reconcile path (not create) runs.
        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function=mock_hog_function,
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(
                StripeSource, "create_webhook", return_value=WebhookCreationResult(success=True)
            ) as mock_create_webhook,
            mock.patch.object(
                StripeSource, "sync_webhook_events", return_value=WebhookSyncResult(success=True)
            ) as mock_sync_events,
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        # Existing webhook: reconcile events, never re-create.
        mock_sync_events.assert_called_once()
        mock_create_webhook.assert_not_called()

    def test_update_schema_to_webhook_existing_function_reconcile_failure_does_not_block(self):
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
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(
                StripeSource,
                "sync_webhook_events",
                return_value=WebhookSyncResult(success=False, error="add Write permission"),
            ),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        # Reconcile failure must not hard-fail the schema enable.
        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK

    def test_update_schema_to_webhook_reconcile_raising_does_not_block(self):
        # The dangerous case: sync_webhook_events RAISES (bad creds, OAuth expired, network)
        # before any internal handling. This must never roll back the schema enable.
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
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            mock.patch.object(StripeSource, "sync_webhook_events", side_effect=ValueError("Missing Stripe API key")),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_webhook_schemas),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
                data={"sync_type": "webhook", "incremental_field": "created", "incremental_field_type": "integer"},
            )

        assert response.status_code == 200
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK

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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function"
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function"
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function"
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch.object(StripeSource, "get_schemas", return_value=mock_non_webhook_schemas),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function"
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

        # Creating a source syncs managed Revenue Analytics views into a DAG, leaving Node rows whose
        # saved_query FK is PROTECT. Team cascades to DataWarehouseSavedQuery, so the nodes/edges must
        # go first — same ordering production relies on in delete_bulky_postgres_data.
        Edge.objects.filter(team=team).delete()
        Node.objects.filter(team=team).delete()
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
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

        with mock.patch("products.data_warehouse.backend.presentation.views.external_data_schema.Database.create_for"):
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

    def test_update_schema_exposes_direct_snowflake_table_without_sync_type(
        self, team, user, client: HttpClient, temporal
    ):
        # Exercises the Snowflake reproject branch: a non-Postgres direct source must rebuild via the
        # Snowflake helper (DIRECT_SNOWFLAKE_URL_PATTERN), not silently fall through to the MySQL one.
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.SNOWFLAKE,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"database": "ANALYTICS"},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="SALES.ACCOUNTS",
            should_sync=False,
            sync_type=None,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "ID", "data_type": "NUMBER", "is_nullable": False}],
                    "foreign_keys": [],
                    "source_catalog": "ANALYTICS",
                    "source_schema": "SALES",
                    "source_table_name": "ACCOUNTS",
                }
            },
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists"
            ) as mock_external_data_workflow_exists,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
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
            assert schema.table.url_pattern == DIRECT_SNOWFLAKE_URL_PATTERN
            mock_external_data_workflow_exists.assert_not_called()
            mock_sync_external_data_job_workflow.assert_not_called()

    def test_update_schema_hides_direct_snowflake_table_when_disabled(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            status=ExternalDataSource.Status.RUNNING,
            source_type=ExternalDataSourceType.SNOWFLAKE,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"database": "ANALYTICS"},
        )
        table = DataWarehouseTable.objects.create(
            name="SALES.ACCOUNTS",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=team,
            url_pattern=DIRECT_SNOWFLAKE_URL_PATTERN,
            external_data_source=source,
            columns={"ID": {"clickhouse": "Int64", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team=team,
            source=source,
            name="SALES.ACCOUNTS",
            should_sync=True,
            sync_type=None,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [{"name": "ID", "data_type": "NUMBER", "is_nullable": False}],
                    "foreign_keys": [],
                }
            },
        )

        with mock.patch("products.data_warehouse.backend.presentation.views.external_data_schema.Database.create_for"):
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
                "primary_key_columns": ["id"],
                "schema_metadata": {
                    "columns": [{"name": "id", "data_type": "integer", "is_nullable": False}],
                    "foreign_keys": [],
                    "source_schema": "analytics",
                    "source_table_name": "events",
                },
            },
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
            ) as mock_add_table,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_cdc_extraction_schedule"
            ),
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
        # The adapter reads the publication name from config itself, so the call is
        # (source, schema, table).
        mock_add_table.assert_called_once()
        assert mock_add_table.call_args.args == (source, "analytics", "events")

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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow",
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
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.trigger_external_data_workflow",
            ) as mock_trigger,
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow",
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

    def test_update_cdc_schema_reenable_triggers_reset_pipeline(self, team, user, client: HttpClient, temporal):
        client.force_login(user)
        source = ExternalDataSource.objects.create(
            team=team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={
                "schema": "public",
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="public.events",
            team=team,
            source=source,
            should_sync=False,
            initial_sync_complete=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming", "primary_key_columns": ["id"]},
        )

        with (
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.is_cdc_enabled_for_team",
                return_value=True,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
                return_value=False,
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
            mock.patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_cdc_extraction_schedule"
            ),
        ):
            response = client.patch(
                f"/api/environments/{team.pk}/external_data_schemas/{schema.id}",
                data={"should_sync": True},
                content_type="application/json",
            )

        assert response.status_code == 200, response.content

        schema.refresh_from_db()
        assert schema.should_sync is True
        # Re-enable must wipe the warehouse table, not merge current rows over stale pre-disable ones.
        assert schema.sync_type_config.get("reset_pipeline") is True
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.initial_sync_complete is False


class TestCancelExternalDataSchema(APIBaseTest):
    @mock.patch("products.data_warehouse.backend.presentation.views.external_data_schema.cancel_external_data_workflow")
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
        from products.warehouse_sources.backend.facade.models import ExternalDataJob

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

    @mock.patch("products.data_warehouse.backend.presentation.views.external_data_schema.cancel_external_data_workflow")
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


class TestSyncTypeConfigLostUpdateProtection(APIBaseTest):
    """The serializer's full-instance save must not revert a sync_type_config key that a concurrent
    CDC extract activity committed after the request loaded the row."""

    def setUp(self):
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            # self_managed so the CDC publication hook in update() returns early without touching the source.
            job_inputs={
                "host": "h",
                "port": 5432,
                "database": "d",
                "user": "u",
                "password": "p",
                "schema": "public",
                "cdc_enabled": True,
                "cdc_management_mode": "self_managed",
                "cdc_slot_name": "s",
                "cdc_publication_name": "p",
            },
        )
        self.schema = ExternalDataSchema.objects.create(
            name="public.orders",
            team=self.team,
            source=self.source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={
                "cdc_mode": "streaming",
                "cdc_table_mode": "consolidated",
                "cdc_last_log_position": "0/100",
                "primary_key_columns": ["id"],
            },
        )

    def test_patch_does_not_clobber_concurrent_activity_position(self):
        from products.data_warehouse.backend.presentation.views.external_data_schema import ExternalDataSchemaSerializer

        # The serializer's in-memory copy is loaded here, holding position 0/100.
        instance = ExternalDataSchema.objects.get(id=self.schema.id)

        # A CDC extract activity commits a newer position while the request is mid-flight.
        update_sync_type_config_keys(self.schema.id, self.team.pk, updates={"cdc_last_log_position": "0/900"})

        # A user PATCH edits an unrelated (non-sync_type_config) field off the stale copy and saves.
        serializer = ExternalDataSchemaSerializer(
            instance,
            data={"enabled_columns": ["id"]},
            partial=True,
            context={"team_id": self.team.pk, "post_commit_actions": []},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        self.schema.refresh_from_db()
        # The user's edit applied AND the concurrent position survived (not reverted to 0/100).
        assert self.schema.enabled_columns == ["id"]
        assert self.schema.sync_type_config["cdc_last_log_position"] == "0/900"

    def test_patch_changing_sync_type_config_key_keeps_concurrent_write(self):
        from products.data_warehouse.backend.presentation.views.external_data_schema import ExternalDataSchemaSerializer

        instance = ExternalDataSchema.objects.get(id=self.schema.id)  # in-memory copy, position 0/100

        # A CDC extract activity commits a newer position while the request is mid-flight.
        update_sync_type_config_keys(self.schema.id, self.team.pk, updates={"cdc_last_log_position": "0/900"})

        # The user changes a sync_type_config key (cdc_table_mode). The re-snapshot it would trigger is
        # deferred to post-commit (which we don't run), so only the merge itself is under test here.
        serializer = ExternalDataSchemaSerializer(
            instance,
            data={"cdc_table_mode": "both"},
            partial=True,
            context={"team_id": self.team.pk, "post_commit_actions": []},
        )
        with mock.patch(
            "products.data_warehouse.backend.presentation.views.external_data_schema.is_any_external_data_schema_paused",
            return_value=False,
        ):
            serializer.is_valid(raise_exception=True)
            serializer.save()

        self.schema.refresh_from_db()
        # The user's key change landed AND the concurrent position (a key the request didn't touch) survived.
        assert self.schema.cdc_table_mode == "both"
        assert self.schema.sync_type_config["cdc_last_log_position"] == "0/900"


class TestAvailableColumnsAcrossSqlSources(APIBaseTest):
    """`available_columns` is source-type-agnostic — it reads `schema_metadata.columns`.
    Parameterized across every SQL source to lock in that the serializer doesn't regress
    to Postgres-only behavior."""

    @parameterized.expand(
        [
            (ExternalDataSourceType.POSTGRES,),
            (ExternalDataSourceType.MYSQL,),
            (ExternalDataSourceType.MSSQL,),
            (ExternalDataSourceType.BIGQUERY,),
            (ExternalDataSourceType.SNOWFLAKE,),
            (ExternalDataSourceType.REDSHIFT,),
        ]
    )
    def test_available_columns_populated_from_schema_metadata(self, source_type: ExternalDataSourceType):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
            sync_type_config={
                "schema_metadata": {
                    "columns": [
                        {"name": "id", "data_type": "integer", "is_nullable": False},
                        {"name": "email", "data_type": "text", "is_nullable": True},
                    ],
                    "foreign_keys": [],
                },
            },
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        payload = response.json()
        assert payload["available_columns"] == [
            {"name": "id", "data_type": "integer", "is_nullable": False},
            {"name": "email", "data_type": "text", "is_nullable": True},
        ]

    @parameterized.expand(
        [
            (ExternalDataSourceType.POSTGRES,),
            (ExternalDataSourceType.MYSQL,),
            (ExternalDataSourceType.MSSQL,),
            (ExternalDataSourceType.BIGQUERY,),
            (ExternalDataSourceType.SNOWFLAKE,),
            (ExternalDataSourceType.REDSHIFT,),
        ]
    )
    def test_available_columns_empty_when_schema_metadata_missing(self, source_type: ExternalDataSourceType):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)
        schema = ExternalDataSchema.objects.create(
            name="customers",
            team=self.team,
            source=source,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["available_columns"] == []

    def test_available_columns_falls_back_to_synced_table_when_metadata_missing(self):
        # `schema_metadata` is empty whenever it hasn't been reconciled (non-SQL sources, or SQL schemas
        # discovered/added after the last reload). available_columns must then fall back to the synced
        # table's columns — otherwise the Descriptions UI shows no columns (even when annotations exist)
        # and users can't edit them. Internal plumbing columns (`_dlt_id`, …) stay hidden.
        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.POSTGRES)
        table = DataWarehouseTable.objects.create(
            name="billing_customer",
            format="DeltaS3Wrapper",
            team=self.team,
            url_pattern="https://bucket.s3/data/*",
            columns={
                "id": {"clickhouse": "String"},
                "balance": {"clickhouse": "Nullable(Int64)"},
                "_dlt_id": {"clickhouse": "String"},
            },
        )
        schema = ExternalDataSchema.objects.create(
            name="billing_customer",
            team=self.team,
            source=source,
            table=table,
            should_sync=True,
            status=ExternalDataSchema.Status.COMPLETED,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/",
        )
        assert response.status_code == 200, response.json()
        # Sort by name: `columns` is JSONB, which doesn't preserve key insertion order.
        assert sorted(response.json()["available_columns"], key=lambda column: column["name"]) == [
            {"name": "balance", "data_type": "Int64", "is_nullable": True},
            {"name": "id", "data_type": "String", "is_nullable": False},
        ]

    @parameterized.expand(
        [
            # source_type, expected — column selection is available for every registered source
            # (SQL projects in its SELECT, others drop before the Delta write) EXCEPT managed-schema
            # sources (Stripe/Paddle/Zendesk), whose canonical HogQL schema needs the full column set.
            (ExternalDataSourceType.POSTGRES, True),
            (ExternalDataSourceType.SNOWFLAKE, True),
            (ExternalDataSourceType.CLICKHOUSE, True),
            (ExternalDataSourceType.HUBSPOT, True),
            (ExternalDataSourceType.STRIPE, False),
            (ExternalDataSourceType.ZENDESK, False),
        ]
    )
    def test_source_supports_column_selection_flag(self, source_type: ExternalDataSourceType, expected: bool):
        source = ExternalDataSource.objects.create(team=self.team, source_type=source_type)

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
        )
        assert response.status_code == 200, response.json()
        assert response.json()["supports_column_selection"] is expected

    def test_enabled_columns_rejected_for_managed_schema_source(self):
        # Stripe/Paddle/Zendesk expose a fixed canonical HogQL schema; dropping a referenced
        # column makes the s3() structure miss it and the query fails to resolve the field.
        # Reject the selection at save so column selection can't corrupt those tables.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(name="Payout", team=self.team, source=source)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"enabled_columns": ["id", "status"]},
        )
        assert response.status_code == 400
        assert "Column selection is not supported" in str(response.json())


class TestExternalDataSchemaRetrieveSource(APIBaseTest):
    def _create(self, source_type: ExternalDataSourceType = ExternalDataSourceType.STRIPE):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(name="Customers", team=self.team, source=source)
        return source, schema

    @parameterized.expand(
        [
            # source_type, expected supports_column_selection, expected supports_row_filters.
            # Stripe is a managed-schema source (no column selection); row filters are SQL-only.
            (ExternalDataSourceType.STRIPE, False, False),
            (ExternalDataSourceType.POSTGRES, True, True),
        ]
    )
    def test_retrieve_includes_source_summary(
        self, source_type: ExternalDataSourceType, expected_column_selection: bool, expected_row_filters: bool
    ):
        source, schema = self._create(source_type=source_type)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 200, response.json()
        summary = response.json()["source"]
        assert summary["id"] == str(source.id)
        assert summary["source_type"] == source_type.value
        assert summary["supports_column_selection"] is expected_column_selection
        assert summary["supports_row_filters"] is expected_row_filters
        assert "user_access_level" in summary

    def test_list_omits_source_summary(self):
        self._create()
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/")
        assert response.status_code == 200
        results = response.json()["results"]
        assert len(results) > 0
        assert all(item["source"] is None for item in results)

    def test_retrieve_cross_team_is_404(self):
        other_team = create_team(organization=self.organization)
        source = ExternalDataSource.objects.create(
            team=other_team, source_type=ExternalDataSourceType.STRIPE, job_inputs={}
        )
        schema = ExternalDataSchema.objects.create(name="Customers", team=other_team, source=source)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 404


class TestExternalDataSchemaRowFilters(APIBaseTest):
    """PATCH-level validation for the row_filters field. A plain row_filters update needs no
    source DB connection or temporal schedule — it only reads the schema's discovered columns."""

    SCHEMA_METADATA = {
        "columns": [
            {"name": "id", "data_type": "integer", "is_nullable": False},
            {"name": "created_at", "data_type": "timestamp", "is_nullable": True},
            {"name": "name", "data_type": "varchar(255)", "is_nullable": True},
            {"name": "geom", "data_type": "geometry", "is_nullable": True},
        ]
    }

    def _create(self) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        # schema_metadata is a read-only property backed by sync_type_config.
        return ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )

    def _patch(self, schema: ExternalDataSchema, row_filters: Any):
        return self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}",
            data={"row_filters": row_filters},
        )

    def test_valid_row_filters_persist(self):
        schema = self._create()
        filters = [
            {"column": "id", "operator": ">", "value": 10},
            {"column": "created_at", "operator": ">=", "value": "2026-01-01"},
        ]
        response = self._patch(schema, filters)
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.row_filters == filters

    def test_null_clears_row_filters(self):
        schema = self._create()
        schema.row_filters = [{"column": "id", "operator": ">", "value": 1}]
        schema.save(update_fields=["row_filters"])
        response = self._patch(schema, None)
        assert response.status_code == 200, response.json()
        schema.refresh_from_db()
        assert schema.row_filters is None

    def test_row_filters_returned_in_serializer(self):
        schema = self._create()
        filters = [{"column": "id", "operator": "<=", "value": 5}]
        schema.row_filters = filters
        schema.save(update_fields=["row_filters"])
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_schemas/{schema.id}/")
        assert response.status_code == 200
        assert response.json()["row_filters"] == filters

    @parameterized.expand(
        [
            ("unknown_column", [{"column": "does_not_exist", "operator": ">", "value": 1}], "Unknown column"),
            ("disallowed_operator", [{"column": "id", "operator": "LIKE", "value": 1}], None),
            ("type_mismatch", [{"column": "id", "operator": ">", "value": "not-an-int"}], None),
            ("bad_date_value", [{"column": "created_at", "operator": ">", "value": "nope"}], None),
            ("unsupported_column_type", [{"column": "geom", "operator": "=", "value": "x"}], None),
        ]
    )
    def test_invalid_row_filter_rejected(self, _name, row_filters, expected_message):
        schema = self._create()
        response = self._patch(schema, row_filters)
        assert response.status_code == 400
        if expected_message:
            assert expected_message in str(response.json())

    @parameterized.expand(
        [
            ("postgres", ExternalDataSourceType.POSTGRES),
            ("mysql", ExternalDataSourceType.MYSQL),
            ("snowflake", ExternalDataSourceType.SNOWFLAKE),
        ]
    )
    def test_row_filters_rejected_for_direct_query_sources(self, _name, source_type):
        # No direct-query executor enforces row filters (they all read the table live), so accepting
        # a filter for any direct engine would silently leave excluded rows visible.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=source_type,
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for direct-query sources" in str(response.json())

    def test_row_filters_rejected_for_source_without_pushdown(self):
        # Only sources that push filters into their query (SQL WHERE) honor them — accepting a
        # filter for an API source would save it and then silently sync unfiltered rows.
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.STRIPE,
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "123"}},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for this source type" in str(response.json())

    def test_row_filters_rejected_for_cdc_schema(self):
        source = ExternalDataSource.objects.create(
            team=self.team,
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "h", "port": "5432", "database": "d", "user": "u", "password": "p", "schema": "public"},
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team=self.team,
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"schema_metadata": self.SCHEMA_METADATA},
        )
        response = self._patch(schema, [{"column": "id", "operator": ">", "value": 10}])
        assert response.status_code == 400
        assert "not supported for CDC" in str(response.json())
