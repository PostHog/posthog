import typing as t
import uuid
from unittest.mock import patch

import psycopg
from django.conf import settings
from django.test import override_settings
from freezegun import freeze_time
from rest_framework import status

from posthog.models import Team
from posthog.models.project import Project
from posthog.temporal.data_imports.pipelines.bigquery import BigQuerySourceConfig
from posthog.temporal.data_imports.pipelines.schemas import (
    PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING,
)
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    BALANCE_TRANSACTION_RESOURCE_NAME as STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRICE_RESOURCE_NAME as STRIPE_PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.temporal.data_imports.pipelines.stripe.settings import ENDPOINTS
from posthog.test.base import APIBaseTest
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.external_data_schema import (
    sync_frequency_interval_to_sync_frequency,
)


class TestExternalDataSource(APIBaseTest):
    def _create_external_data_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="test",
            job_inputs={
                "stripe_secret_key": "sk_test_123",
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    def test_create_external_data_source(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRODUCT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CHARGE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        payload = response.json()

        self.assertEqual(response.status_code, 201)
        # number of schemas should match default schemas for Stripe
        self.assertEqual(
            ExternalDataSchema.objects.filter(source_id=payload["id"]).count(),
            len(PIPELINE_TYPE_SCHEMA_DEFAULT_MAPPING[ExternalDataSource.Type.STRIPE]),
        )

    def test_create_external_data_source_delete_on_missing_schemas(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": False,
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    def test_create_external_data_source_delete_on_bad_schema(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {"name": "SomeOtherSchema", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    def test_prefix_external_data_source(self):
        # Create no prefix

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRODUCT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CHARGE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 201)

        # Try to create same type without prefix again

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRODUCT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CHARGE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Source type already exists. Prefix is required"})

        # Create with prefix
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRODUCT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CHARGE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
                "prefix": "test_",
            },
        )

        self.assertEqual(response.status_code, 201)

        # Try to create same type with same prefix again
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRODUCT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PRICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CHARGE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
                "prefix": "test_",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"message": "Prefix already exists"})

    def test_create_external_data_source_incremental(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_SUBSCRIPTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_PRODUCT_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_PRICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_INVOICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_CHARGE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        },
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_create_external_data_source_incremental_missing_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_SUBSCRIPTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_PRODUCT_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_PRICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_INVOICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                        {
                            "name": STRIPE_CHARGE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field_type": "integer",
                        },
                    ],
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0

    def test_create_external_data_source_incremental_missing_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "client_secret": "sk_test_123",
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_SUBSCRIPTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_PRODUCT_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_PRICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_INVOICE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                        {
                            "name": STRIPE_CHARGE_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                        },
                    ],
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0

    def test_create_external_data_source_bigquery_removes_project_id_prefix(self):
        """Test we remove the `project_id` prefix of a `dataset_id`."""
        with patch("posthog.warehouse.api.external_data_source.get_bigquery_schemas") as mocked_get_bigquery_schemas:
            mocked_get_bigquery_schemas.return_value = {"my_schema": "something"}

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "BigQuery",
                    "payload": {
                        "schemas": [
                            {
                                "name": "my_schema",
                                "should_sync": True,
                                "sync_type": "incremental",
                                "incremental_field": "id",
                                "incremental_field_type": "integer",
                            },
                        ],
                        "dataset_id": "my_project.my_dataset",
                        "key_file": {
                            "project_id": "my_project",
                            "private_key": "my_private_key",
                            "private_key_id": "my_private_key_id",
                            "token_uri": "https://google.com",
                            "client_email": "test@posthog.com",
                        },
                    },
                },
            )
        assert response.status_code == 201
        assert len(ExternalDataSource.objects.all()) == 1

        source = response.json()
        source_model = ExternalDataSource.objects.get(id=source["id"])

        assert source_model.job_inputs["project_id"] == "my_project"
        assert source_model.job_inputs["dataset_id"] == "my_dataset"
        assert source_model.job_inputs["private_key"] == "my_private_key"
        assert source_model.job_inputs["private_key_id"] == "my_private_key_id"

    def test_create_external_data_source_missing_required_bigquery_job_input(self):
        """Test we fail source creation when missing inputs."""
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "BigQuery",
                "payload": {
                    "dataset_id": "my_dataset",
                    "key_file": {
                        "project_id": "my_project",
                        "token_uri": "https://google.com",
                        "client_email": "test@posthog.com",
                    },
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0
        assert response.json()["detail"].startswith("Missing required BigQuery inputs")
        assert "'private_key'" in response.json()["detail"]
        assert "'private_key_id'" in response.json()["detail"]

    def test_list_external_data_source(self):
        self._create_external_data_source()
        self._create_external_data_source()

        with self.assertNumQueries(23):
            response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 2)

    def test_dont_expose_job_inputs(self):
        self._create_external_data_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        payload = response.json()
        results = payload["results"]

        assert len(results) == 1

        result = results[0]
        # we should scrape out `stripe_secret_key` from job_inputs
        assert result.get("job_inputs") == {}

    def test_get_external_data_source_with_schema(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            list(payload.keys()),
            [
                "id",
                "created_at",
                "created_by",
                "status",
                "source_type",
                "latest_error",
                "prefix",
                "revenue_analytics_enabled",
                "last_run_at",
                "schemas",
                "job_inputs",
            ],
        )
        self.assertEqual(
            payload["schemas"],
            [
                {
                    "id": str(schema.pk),
                    "incremental": False,
                    "incremental_field": None,
                    "incremental_field_type": None,
                    "last_synced_at": schema.last_synced_at,
                    "name": schema.name,
                    "latest_error": schema.latest_error,
                    "should_sync": schema.should_sync,
                    "status": schema.status,
                    "sync_type": schema.sync_type,
                    "table": schema.table,
                    "sync_frequency": sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval),
                    "sync_time_of_day": schema.sync_time_of_day,
                }
            ],
        )

    def test_delete_external_data_source(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204

        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()
        assert ExternalDataSchema.objects.filter(pk=schema.pk, deleted=True).exists()

    # TODO: update this test
    @patch("posthog.warehouse.api.external_data_source.trigger_external_data_source_workflow")
    def test_reload_external_data_source(self, mock_trigger):
        source = self._create_external_data_source()

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/reload/")

        source.refresh_from_db()

        self.assertEqual(mock_trigger.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(source.status, "Running")

    def test_database_schema(self):
        postgres_connection = psycopg.connect(
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            dbname=settings.PG_DATABASE,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
        )

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS posthog_test (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(50)
                );
                """
            )

            postgres_connection.commit()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
            data={
                "source_type": "Postgres",
                "host": settings.PG_HOST,
                "port": int(settings.PG_PORT),
                "database": settings.PG_DATABASE,
                "user": settings.PG_USER,
                "password": settings.PG_PASSWORD,
                "schema": "public",
            },
        )
        results = response.json()

        self.assertEqual(response.status_code, 200)

        table_names = [table["table"] for table in results]
        self.assertTrue("posthog_test" in table_names)

        with postgres_connection.cursor() as cursor:
            cursor.execute(
                """
                DROP TABLE posthog_test;
                """
            )
            postgres_connection.commit()

        postgres_connection.close()

    def test_database_schema_stripe_credentials(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "client_secret": "blah",
                    "account_id": "blah",
                },
            )

            assert response.status_code == 200

    def test_database_schema_stripe_credentials_sad_path(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.side_effect = Exception("Invalid API key")

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "stripe_secret_key": "invalid_key",
                },
            )

            assert response.status_code == 400
            assert response.json()["message"] == "Invalid credentials: Stripe secret is incorrect"

    def test_database_schema_stripe_permissions_error(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            from posthog.temporal.data_imports.pipelines.stripe import (
                StripePermissionError,
            )

            missing_permissions = {"Account": "Error message for Account", "Invoice": "Error message for Invoice"}
            validate_credentials_mock.side_effect = StripePermissionError(missing_permissions)

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "stripe_secret_key": "invalid_key",
                },
            )

            assert response.status_code == 400
            assert "Stripe API key lacks permissions for Account, Invoice" in response.json()["message"]

    def test_database_schema_zendesk_credentials(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_zendesk_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Zendesk",
                    "subdomain": "blah",
                    "api_key": "blah",
                    "email_address": "blah",
                },
            )

            assert response.status_code == 200

    def test_database_schema_zendesk_credentials_sad_path(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_zendesk_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = False

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Zendesk",
                    "subdomain": "blah",
                    "api_key": "blah",
                    "email_address": "blah",
                },
            )

            assert response.status_code == 400

    def test_database_schema_non_postgres_source(self):
        with patch(
            "posthog.warehouse.api.external_data_source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                },
            )
            results = response.json()

            self.assertEqual(response.status_code, 200)

            table_names = [table["table"] for table in results]
            for table in ENDPOINTS:
                assert table in table_names

    @patch(
        "posthog.warehouse.api.external_data_source.get_sql_schemas_for_source_type",
        return_value={"table_1": [("id", "integer")]},
    )
    @patch(
        "posthog.warehouse.api.external_data_source.get_postgres_row_count",
        return_value={"table_1": 42},
    )
    def test_internal_postgres(self, patch_get_sql_schemas_for_source_type, patch_get_postgres_row_count):
        # This test checks handling of project ID 2 in Cloud US and project ID 1 in Cloud EU,
        # so let's make sure there are no projects with these IDs in the test DB
        Project.objects.filter(id__in=[1, 2]).delete()
        Team.objects.filter(id__in=[1, 2]).delete()

        with override_settings(CLOUD_DEPLOYMENT="US"):
            team_2 = Team.objects.create(id=2, organization=self.team.organization)
            response = self.client.post(
                f"/api/environments/{team_2.id}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "database": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            assert response.status_code == 200
            assert response.json() == [
                {
                    "table": "table_1",
                    "should_sync": False,
                    "rows": 42,
                    "incremental_fields": [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}],
                    "incremental_available": True,
                    "incremental_field": "id",
                    "sync_type": None,
                }
            ]

            new_team = Team.objects.create(id=984961485, name="new_team", organization=self.team.organization)

            response = self.client.post(
                f"/api/environments/{new_team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "database": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"message": "Cannot use internal database"})

        with override_settings(CLOUD_DEPLOYMENT="EU"):
            team_1 = Team.objects.create(id=1, organization=self.team.organization)
            response = self.client.post(
                f"/api/environments/{team_1.id}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "rows": 42,
                    "port": int(settings.PG_PORT),
                    "database": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )

            assert response.status_code == 200
            assert response.json() == [
                {
                    "table": "table_1",
                    "should_sync": False,
                    "rows": 42,
                    "incremental_fields": [{"label": "id", "type": "integer", "field": "id", "field_type": "integer"}],
                    "incremental_available": True,
                    "incremental_field": "id",
                    "sync_type": None,
                }
            ]

            new_team = Team.objects.create(id=984961486, name="new_team", organization=self.team.organization)

            response = self.client.post(
                f"/api/environments/{new_team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "host": "172.16.0.0",
                    "port": int(settings.PG_PORT),
                    "database": settings.PG_DATABASE,
                    "user": settings.PG_USER,
                    "password": settings.PG_PASSWORD,
                    "schema": "public",
                },
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"message": "Cannot use internal database"})

    def test_source_jobs(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)
        job = ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            workflow_run_id="test_run_id",
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs",
        )

        data = response.json()

        assert response.status_code, status.HTTP_200_OK
        assert len(data) == 1
        assert data[0]["id"] == str(job.pk)
        assert data[0]["status"] == "Completed"
        assert data[0]["rows_synced"] == 100
        assert data[0]["schema"]["id"] == str(schema.pk)
        assert data[0]["workflow_run_id"] is not None

    def test_source_jobs_billable_job(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            workflow_run_id="test_run_id",
            pipeline_version=ExternalDataJob.PipelineVersion.V2,
            billable=False,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs",
        )

        data = response.json()

        assert response.status_code, status.HTTP_200_OK
        assert len(data) == 0

    def test_source_jobs_pagination(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)
        with freeze_time("2024-07-01T12:00:00.000Z"):
            job1 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

            response = self.client.get(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job1.pk)

        # Query newer jobs
        with freeze_time("2024-07-01T18:00:00.000Z"):
            job2 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

            response = self.client.get(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs?after=2024-07-01T12:00:00.000Z",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job2.pk)

        # Query older jobs
        with freeze_time("2024-07-01T09:00:00.000Z"):
            job3 = ExternalDataJob.objects.create(
                team=self.team,
                pipeline=source,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=100,
                workflow_run_id="test_run_id",
                pipeline_version=ExternalDataJob.PipelineVersion.V1,
            )

            response = self.client.get(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs?before=2024-07-01T12:00:00.000Z",
            )

            data = response.json()

            assert response.status_code, status.HTTP_200_OK
            assert len(data) == 1
            assert data[0]["id"] == str(job3.pk)

    def test_trimming_payload(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "stripe_secret_key": "  sk_test_123   ",
                    "stripe_account_id": "  blah   ",
                    "schemas": [
                        {"name": "BalanceTransaction", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        payload = response.json()

        assert response.status_code == 201

        source = ExternalDataSource.objects.get(id=payload["id"])
        assert source.job_inputs is not None

        assert source.job_inputs["stripe_secret_key"] == "sk_test_123"
        assert source.job_inputs["stripe_account_id"] == "blah"

    def test_update_then_get_external_data_source_with_ssh_tunnel(self):
        """Test that updating a source with SSH tunnel info properly normalizes the structure and
        manipulates the flattened structure.
        """
        # First create a source without SSH tunnel
        source = self._create_external_data_source()

        # Update with SSH tunnel config
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
            data={
                "job_inputs": {
                    "ssh-tunnel": {
                        "enabled": True,
                        "host": "ssh.example.com",
                        "port": 22,
                        "auth_type": {
                            "selection": "username_password",
                            "username": "testuser",
                            "password": "testpass",
                            "passphrase": "testphrase",
                            "private_key": "testkey",
                        },
                    }
                },
            },
        )

        assert response.status_code == 200

        # Verify the SSH tunnel config was normalized correctly
        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel_enabled"] == "True"
        assert source.job_inputs["ssh_tunnel_host"] == "ssh.example.com"
        assert source.job_inputs["ssh_tunnel_port"] == "22"
        assert source.job_inputs["ssh_tunnel_auth_type"] == "username_password"
        assert source.job_inputs["ssh_tunnel_auth_type_username"] == "testuser"
        assert source.job_inputs["ssh_tunnel_auth_type_password"] == "testpass"
        assert source.job_inputs["ssh_tunnel_auth_type_passphrase"] == "testphrase"
        assert source.job_inputs["ssh_tunnel_auth_type_private_key"] == "testkey"

        # Test the to_representation from flattened to nested structure
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 200
        data = response.json()

        assert "job_inputs" in data
        assert "ssh-tunnel" in data["job_inputs"]
        ssh_tunnel = data["job_inputs"]["ssh-tunnel"]

        assert ssh_tunnel["enabled"] == "True"
        assert ssh_tunnel["host"] == "ssh.example.com"
        assert ssh_tunnel["port"] == "22"
        assert "auth_type" in ssh_tunnel
        assert ssh_tunnel["auth_type"]["selection"] == "username_password"
        assert ssh_tunnel["auth_type"]["username"] == "testuser"
        assert ssh_tunnel["auth_type"]["password"] is None
        assert ssh_tunnel["auth_type"]["passphrase"] is None
        assert ssh_tunnel["auth_type"]["private_key"] is None

    def test_snowflake_auth_type_create_and_update(self):
        """Test that we can create and update the auth type for a Snowflake source"""
        with patch("posthog.warehouse.api.external_data_source.get_snowflake_schemas") as mocked_get_snowflake_schemas:
            mocked_get_snowflake_schemas.return_value = {"my_table": "something"}

            # Create a Snowflake source with password auth
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "prefix": "",
                    "payload": {
                        "source_type": "Snowflake",
                        "account_id": "my_account_id",
                        "database": "my_database",
                        "warehouse": "my_warehouse",
                        "auth_type": {
                            "selection": "password",
                            "username": "my_username",
                            "password": "my_password",
                            "private_key": "",
                            "passphrase": "",
                        },
                        "role": "my_role",
                        "schema": "my_schema",
                        "schemas": [
                            {
                                "name": "my_table",
                                "should_sync": True,
                                "sync_type": "full_refresh",
                                "incremental_field": None,
                                "incremental_field_type": None,
                            },
                        ],
                    },
                    "source_type": "Snowflake",
                },
            )
        assert response.status_code == 201, response.json()
        assert len(ExternalDataSource.objects.all()) == 1

        source = response.json()
        source_model = ExternalDataSource.objects.get(id=source["id"])

        assert source_model.job_inputs is not None
        job_inputs: dict[str, t.Any] = source_model.job_inputs
        assert job_inputs["account_id"] == "my_account_id"
        assert job_inputs["database"] == "my_database"
        assert job_inputs["warehouse"] == "my_warehouse"
        assert job_inputs["auth_type"] == "password"
        assert job_inputs["user"] == "my_username"
        assert job_inputs["password"] == "my_password"
        assert job_inputs["passphrase"] == ""
        assert job_inputs["private_key"] == ""
        assert job_inputs["role"] == "my_role"
        assert job_inputs["schema"] == "my_schema"

        # Update the source with a new auth type
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
            data={
                "job_inputs": {
                    "role": "my_role",
                    "user": "my_username",
                    "schema": "my_schema",
                    "database": "my_database",
                    "warehouse": "my_warehouse",
                    "account_id": "my_account_id",
                    "auth_type": {
                        "selection": "keypair",
                        "username": "my_username",
                        "private_key": "my_private_key",
                        "passphrase": "my_passphrase",
                    },
                }
            },
        )

        assert response.status_code == 200, response.json()

        source_model.refresh_from_db()

        assert source_model.job_inputs is not None
        job_inputs = source_model.job_inputs
        assert job_inputs["account_id"] == "my_account_id"
        assert job_inputs["database"] == "my_database"
        assert job_inputs["warehouse"] == "my_warehouse"
        assert job_inputs["auth_type"] == "keypair"
        assert job_inputs["user"] == "my_username"
        assert job_inputs["passphrase"] == "my_passphrase"
        assert job_inputs["private_key"] == "my_private_key"
        assert job_inputs["role"] == "my_role"
        assert job_inputs["schema"] == "my_schema"

    def test_bigquery_create_and_update(self):
        """Test that we can create and update the config for a BigQuery source"""
        with patch("posthog.warehouse.api.external_data_source.get_bigquery_schemas") as mocked_get_bigquery_schemas:
            mocked_get_bigquery_schemas.return_value = {"my_table": "something"}

            # Create a BigQuery source
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "prefix": "",
                    "payload": {
                        "source_type": "BigQuery",
                        "key_file": {
                            "type": "service_account",
                            "project_id": "dummy_project_id",
                            "private_key_id": "dummy_private_key_id",
                            "private_key": "dummy_private_key",
                            "client_email": "dummy_client_email",
                            "client_id": "dummy_client_id",
                            "auth_uri": "dummy_auth_uri",
                            "token_uri": "dummy_token_uri",
                            "auth_provider_x509_cert_url": "dummy_auth_provider_x509_cert_url",
                            "client_x509_cert_url": "dummy_client_x509_cert_url",
                            "universe_domain": "dummy_universe_domain",
                        },
                        "dataset_id": "dummy_dataset_id",
                        "temporary-dataset": {"enabled": False, "temporary_dataset_id": ""},
                        "dataset_project": {"enabled": False, "dataset_project_id": ""},
                        "schemas": [
                            {
                                "name": "my_table",
                                "should_sync": True,
                                "sync_type": "full_refresh",
                                "incremental_field": None,
                                "incremental_field_type": None,
                            },
                        ],
                    },
                    "source_type": "BigQuery",
                },
            )
        assert response.status_code == 201, response.json()
        assert len(ExternalDataSource.objects.all()) == 1

        source = response.json()
        source_model = ExternalDataSource.objects.get(id=source["id"])

        assert source_model.job_inputs is not None
        job_inputs: dict[str, t.Any] = source_model.job_inputs

        # validate against the actual class we use in the Temporal activity
        bq_config = BigQuerySourceConfig.from_dict(job_inputs)

        assert bq_config.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.private_key == "dummy_private_key"
        assert bq_config.private_key_id == "dummy_private_key_id"
        assert bq_config.client_email == "dummy_client_email"
        assert bq_config.token_uri == "dummy_token_uri"
        assert bq_config.using_temporary_dataset is False
        assert bq_config.temporary_dataset_id == ""

        # # Update the source by adding a temporary dataset
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
            data={
                "job_inputs": {
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "dataset_id": "dummy_dataset_id",
                    "project_id": "dummy_project_id",
                    "client_email": "dummy_client_email",
                    "temporary-dataset": {"enabled": True, "temporary_dataset_id": "dummy_temporary_dataset_id"},
                    "dataset_project": {"enabled": False, "dataset_project_id": ""},
                    "key_file": {
                        "type": "service_account",
                        "project_id": "dummy_project_id",
                        "private_key_id": "dummy_private_key_id",
                        "private_key": "dummy_private_key",
                        "client_email": "dummy_client_email",
                        "client_id": "dummy_client_id",
                        "auth_uri": "dummy_auth_uri",
                        "token_uri": "dummy_token_uri",
                        "auth_provider_x509_cert_url": "dummy_auth_provider_x509_cert_url",
                        "client_x509_cert_url": "dummy_client_x509_cert_url",
                        "universe_domain": "dummy_universe_domain",
                    },
                }
            },
        )

        assert response.status_code == 200, response.json()

        source_model.refresh_from_db()

        # validate against the actual class we use in the Temporal activity
        bq_config = BigQuerySourceConfig.from_dict(source_model.job_inputs)

        assert bq_config.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.private_key == "dummy_private_key"
        assert bq_config.private_key_id == "dummy_private_key_id"
        assert bq_config.client_email == "dummy_client_email"
        assert bq_config.token_uri == "dummy_token_uri"
        assert bq_config.using_temporary_dataset is True
        assert bq_config.temporary_dataset_id == "dummy_temporary_dataset_id"

        # # Update the source by adding dataset project id
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
            data={
                "job_inputs": {
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "dataset_id": "dummy_dataset_id",
                    "project_id": "dummy_project_id",
                    "client_email": "dummy_client_email",
                    "temporary-dataset": {"enabled": False, "temporary_dataset_id": ""},
                    "dataset_project": {"enabled": True, "dataset_project_id": "other_project_id"},
                    "key_file": {
                        "type": "service_account",
                        "project_id": "dummy_project_id",
                        "private_key_id": "dummy_private_key_id",
                        "private_key": "dummy_private_key",
                        "client_email": "dummy_client_email",
                        "client_id": "dummy_client_id",
                        "auth_uri": "dummy_auth_uri",
                        "token_uri": "dummy_token_uri",
                        "auth_provider_x509_cert_url": "dummy_auth_provider_x509_cert_url",
                        "client_x509_cert_url": "dummy_client_x509_cert_url",
                        "universe_domain": "dummy_universe_domain",
                    },
                }
            },
        )

        assert response.status_code == 200, response.json()

        source_model.refresh_from_db()

        # validate against the actual class we use in the Temporal activity
        bq_config = BigQuerySourceConfig.from_dict(source_model.job_inputs)

        assert bq_config.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.private_key == "dummy_private_key"
        assert bq_config.private_key_id == "dummy_private_key_id"
        assert bq_config.client_email == "dummy_client_email"
        assert bq_config.token_uri == "dummy_token_uri"
        assert bq_config.using_temporary_dataset is False
        assert bq_config.using_custom_dataset_project is True
        assert bq_config.dataset_project_id == "other_project_id"
