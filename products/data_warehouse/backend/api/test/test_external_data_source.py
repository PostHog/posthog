import uuid
import typing as t

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import psycopg
from rest_framework import status

from posthog.models import Team
from posthog.models.project import Project
from posthog.temporal.data_imports.sources.bigquery.bigquery import BigQuerySourceConfig
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
from posthog.temporal.data_imports.sources.stripe.settings import ENDPOINTS as STRIPE_ENDPOINTS

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import sync_frequency_interval_to_sync_frequency
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig


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
                    "stripe_secret_key": "sk_test_123",
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
                        {"name": STRIPE_REFUND_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CREDIT_NOTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_ITEM_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PAYOUT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISPUTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {
                            "name": STRIPE_CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                        {
                            "name": STRIPE_CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                        },
                    ],
                },
            },
        )
        payload = response.json()

        self.assertEqual(response.status_code, 201)
        # number of schemas should match default schemas for Stripe
        self.assertEqual(
            ExternalDataSchema.objects.filter(source_id=payload["id"]).count(),
            len(STRIPE_ENDPOINTS),
        )

    def test_create_external_data_source_delete_on_missing_schemas(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "stripe_secret_key": "sk_test_123",
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
                    "stripe_secret_key": "sk_test_123",
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
                    "stripe_secret_key": "sk_test_123",
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
                        {"name": STRIPE_REFUND_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CREDIT_NOTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_ITEM_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PAYOUT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISPUTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
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
                    "stripe_secret_key": "sk_test_123",
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
                        {"name": STRIPE_REFUND_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CREDIT_NOTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_ITEM_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PAYOUT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISPUTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
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
                    "stripe_secret_key": "sk_test_123",
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
                        {"name": STRIPE_REFUND_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CREDIT_NOTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_ITEM_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PAYOUT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISPUTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
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
                    "stripe_secret_key": "sk_test_123",
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
                        {"name": STRIPE_REFUND_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_CREDIT_NOTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_INVOICE_ITEM_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_PAYOUT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISPUTE_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
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
                    "stripe_secret_key": "sk_test_123",
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
                    "stripe_secret_key": "sk_test_123",
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
                    "stripe_secret_key": "sk_test_123",
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
        with patch(
            "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas"
        ) as mocked_get_bigquery_schemas:
            mocked_get_bigquery_schemas.return_value = {"my_table": [("something", "DATE")]}

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "BigQuery",
                    "payload": {
                        "schemas": [
                            {
                                "name": "my_table",
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

        assert source_model.job_inputs["key_file"]["project_id"] == "my_project"
        assert source_model.job_inputs["key_file"]["private_key"] == "my_private_key"
        assert source_model.job_inputs["key_file"]["private_key_id"] == "my_private_key_id"
        assert source_model.job_inputs["dataset_id"] == "my_project.my_dataset"

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
        assert response.json()["message"].startswith("Invalid source config")
        assert "'private_key'" in response.json()["message"]
        assert "'private_key_id'" in response.json()["message"]

    def test_list_external_data_source(self):
        self._create_external_data_source()
        self._create_external_data_source()

        with self.assertNumQueries(25):
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
                "last_run_at",
                "schemas",
                "job_inputs",
                "revenue_analytics_config",
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
    @patch("products.data_warehouse.backend.api.external_data_source.trigger_external_data_source_workflow")
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
            "posthog.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "stripe_secret_key": "blah",
                    "stripe_account_id": "blah",
                },
            )

            assert response.status_code == 200

    def test_database_schema_stripe_credentials_sad_path(self):
        with patch(
            "posthog.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
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
            assert "Invalid API key" in response.json()["message"]

    def test_database_schema_stripe_permissions_error(self):
        with patch(
            "posthog.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            from posthog.temporal.data_imports.sources.stripe.stripe import StripePermissionError

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
            "posthog.temporal.data_imports.sources.zendesk.source.validate_credentials"
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
            "posthog.temporal.data_imports.sources.zendesk.source.validate_credentials"
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
            "posthog.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            validate_credentials_mock.return_value = True
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "stripe_secret_key": "sk_test_123",
                    "stripe_account_id": "blah",
                },
            )
            results = response.json()

            self.assertEqual(response.status_code, 200)

            table_names = [table["table"] for table in results]
            for table in STRIPE_ENDPOINTS:
                assert table in table_names

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
        return_value={"table_1": [("id", "integer")]},
    )
    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.get_postgres_row_count",
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
                    "append_available": True,
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
            self.assertEqual(response.json(), {"message": "Hosts with internal IP addresses are not allowed"})

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
                    "append_available": True,
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
            self.assertEqual(response.json(), {"message": "Hosts with internal IP addresses are not allowed"})

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
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            job_inputs={
                "source_type": "Postgres",
                "host": "172.16.0.0",
                "port": "123",
                "database": "database",
                "user": "user",
                "password": "password",
                "schema": "public",
            },
        )

        # Update with SSH tunnel config
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
            data={
                "job_inputs": {
                    "ssh_tunnel": {
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
        assert source.job_inputs["ssh_tunnel"]["enabled"] == "True"
        assert source.job_inputs["ssh_tunnel"]["host"] == "ssh.example.com"
        assert source.job_inputs["ssh_tunnel"]["port"] == "22"
        assert source.job_inputs["ssh_tunnel"]["auth"]["type"] == "username_password"
        assert source.job_inputs["ssh_tunnel"]["auth"]["username"] == "testuser"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "testpass"
        assert source.job_inputs["ssh_tunnel"]["auth"]["passphrase"] == "testphrase"
        assert source.job_inputs["ssh_tunnel"]["auth"]["private_key"] == "testkey"

        # Test the to_representation from flattened to nested structure
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 200
        data = response.json()

        assert "job_inputs" in data
        assert "ssh_tunnel" in data["job_inputs"]
        ssh_tunnel = data["job_inputs"]["ssh_tunnel"]

        assert ssh_tunnel["enabled"] == "True"
        assert ssh_tunnel["host"] == "ssh.example.com"
        assert ssh_tunnel["port"] == "22"
        assert "auth" in ssh_tunnel
        assert ssh_tunnel["auth"]["selection"] == "username_password"
        assert ssh_tunnel["auth"]["username"] == "testuser"
        assert ssh_tunnel["auth"]["password"] is None
        assert ssh_tunnel["auth"]["passphrase"] is None
        assert ssh_tunnel["auth"]["private_key"] is None

    def test_snowflake_auth_type_create_and_update(self):
        """Test that we can create and update the auth type for a Snowflake source"""
        with patch(
            "posthog.temporal.data_imports.sources.snowflake.source.get_snowflake_schemas"
        ) as mocked_get_snowflake_schemas:
            mocked_get_snowflake_schemas.return_value = {"my_table": [("something", "DATE")]}

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
                            "user": "my_username",
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
        assert job_inputs["role"] == "my_role"
        assert job_inputs["schema"] == "my_schema"
        assert job_inputs["database"] == "my_database"
        assert job_inputs["warehouse"] == "my_warehouse"
        assert job_inputs["account_id"] == "my_account_id"
        assert job_inputs["auth_type"]["selection"] == "password"
        assert job_inputs["auth_type"]["user"] == "my_username"
        assert job_inputs["auth_type"]["password"] == "my_password"
        assert job_inputs["auth_type"]["passphrase"] == ""
        assert job_inputs["auth_type"]["private_key"] == ""

        # Update the source with a new auth type
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
            data={
                "job_inputs": {
                    "role": "my_role",
                    "schema": "my_schema",
                    "database": "my_database",
                    "warehouse": "my_warehouse",
                    "account_id": "my_account_id",
                    "auth_type": {
                        "selection": "keypair",
                        "user": "my_username",
                        "private_key": "my_private_key",
                        "passphrase": "my_passphrase",
                        "password": "",
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
        assert job_inputs["role"] == "my_role"
        assert job_inputs["schema"] == "my_schema"
        assert job_inputs["auth_type"]["selection"] == "keypair"
        assert job_inputs["auth_type"]["user"] == "my_username"
        assert job_inputs["auth_type"]["passphrase"] == "my_passphrase"
        assert job_inputs["auth_type"]["private_key"] == "my_private_key"

    def test_bigquery_create_and_update(self):
        """Test that we can create and update the config for a BigQuery source"""
        with patch(
            "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas"
        ) as mocked_get_bigquery_schemas:
            mocked_get_bigquery_schemas.return_value = {"my_table": [("something", "DATE")]}

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

        assert bq_config.key_file.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.key_file.private_key == "dummy_private_key"
        assert bq_config.key_file.private_key_id == "dummy_private_key_id"
        assert bq_config.key_file.client_email == "dummy_client_email"
        assert bq_config.key_file.token_uri == "dummy_token_uri"
        assert bq_config.temporary_dataset is not None
        assert bq_config.temporary_dataset.enabled is False
        assert bq_config.temporary_dataset.temporary_dataset_id == ""

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

        assert bq_config.key_file.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.key_file.private_key == "dummy_private_key"
        assert bq_config.key_file.private_key_id == "dummy_private_key_id"
        assert bq_config.key_file.client_email == "dummy_client_email"
        assert bq_config.key_file.token_uri == "dummy_token_uri"
        assert bq_config.temporary_dataset is not None
        assert bq_config.temporary_dataset.enabled is True
        assert bq_config.temporary_dataset.temporary_dataset_id == "dummy_temporary_dataset_id"

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

        assert bq_config.key_file.project_id == "dummy_project_id"
        assert bq_config.dataset_id == "dummy_dataset_id"
        assert bq_config.key_file.private_key == "dummy_private_key"
        assert bq_config.key_file.private_key_id == "dummy_private_key_id"
        assert bq_config.key_file.client_email == "dummy_client_email"
        assert bq_config.key_file.token_uri == "dummy_token_uri"
        assert bq_config.temporary_dataset is not None
        assert bq_config.temporary_dataset.enabled is False
        assert bq_config.dataset_project is not None
        assert bq_config.dataset_project.enabled is True
        assert bq_config.dataset_project.dataset_project_id == "other_project_id"

    def test_get_wizard_sources(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/wizard")
        payload = response.json()
        assert response.status_code == 200
        assert payload is not None

    def test_revenue_analytics_config_created_automatically(self):
        """Test that revenue analytics config is created automatically when external data source is created."""
        source = self._create_external_data_source()

        # Config should be created automatically
        assert hasattr(source, "revenue_analytics_config")
        config = source.revenue_analytics_config
        assert isinstance(config, ExternalDataSourceRevenueAnalyticsConfig)
        assert config.external_data_source == source
        assert config.enabled is True  # Stripe should be enabled by default
        assert config.include_invoiceless_charges is True

    def test_revenue_analytics_config_safe_property(self):
        """Test that the safe property always returns a config even if it doesn't exist."""
        source = self._create_external_data_source()

        # Delete the config to test fallback
        ExternalDataSourceRevenueAnalyticsConfig.objects.filter(external_data_source=source).delete()

        # Safe property should recreate it
        config = source.revenue_analytics_config_safe
        assert isinstance(config, ExternalDataSourceRevenueAnalyticsConfig)
        assert config.external_data_source == source
        assert config.enabled is True  # Stripe should be enabled by default

    def test_revenue_analytics_config_in_api_response(self):
        """Test that revenue analytics config is included in API responses."""
        source = self._create_external_data_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        payload = response.json()

        assert response.status_code == 200
        assert "revenue_analytics_config" in payload
        config_data = payload["revenue_analytics_config"]
        assert config_data["enabled"] is True
        assert config_data["include_invoiceless_charges"] is True

    def test_update_revenue_analytics_config(self):
        """Test updating revenue analytics config via PATCH endpoint."""
        source = self._create_external_data_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/revenue_analytics_config/",
            data={
                "enabled": False,
                "include_invoiceless_charges": False,
            },
        )

        assert response.status_code == 200

        # Check the response includes updated config
        payload = response.json()
        assert "revenue_analytics_config" in payload
        config_data = payload["revenue_analytics_config"]
        assert config_data["enabled"] is False
        assert config_data["include_invoiceless_charges"] is False

        # Verify in database
        source.refresh_from_db()
        config = source.revenue_analytics_config
        assert config.enabled is False
        assert config.include_invoiceless_charges is False

    def test_revenue_analytics_config_partial_update(self):
        """Test partial update of revenue analytics config."""
        source = self._create_external_data_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/revenue_analytics_config/",
            data={"enabled": False},
        )

        assert response.status_code == 200

        # Check only enabled was updated
        source.refresh_from_db()
        config = source.revenue_analytics_config
        assert config.enabled is False
        assert config.include_invoiceless_charges is True  # Should remain unchanged

    def test_revenue_analytics_config_queryset_optimization(self):
        """Test that the manager uses select_related for efficient queries."""
        self._create_external_data_source()
        self._create_external_data_source()

        # This should use select_related to fetch configs efficiently
        with self.assertNumQueries(1):
            sources = list(ExternalDataSource.objects.all())
            for source in sources:
                # This should not trigger additional queries due to select_related
                _ = source.revenue_analytics_config.enabled

    def test_create_external_data_source_rejects_invalid_prefix(self):
        """Test that invalid characters in prefix are rejected."""
        invalid_prefixes = [
            ("email@domain.com", "@"),
            ("test-prefix", "hyphen"),
            ("123_start", "number"),
            ("test prefix", "space"),
            ("test.prefix", "dot"),
            ("test/prefix", "slash"),
            ("___", "underscores only"),
        ]

        for prefix, reason in invalid_prefixes:
            with self.subTest(prefix=prefix, reason=reason):
                response = self.client.post(
                    f"/api/environments/{self.team.pk}/external_data_sources/",
                    data={
                        "source_type": "Stripe",
                        "prefix": prefix,
                        "payload": {
                            "stripe_secret_key": "sk_test_123",
                            "schemas": [
                                {
                                    "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                                    "should_sync": True,
                                    "sync_type": "full_refresh",
                                },
                            ],
                        },
                    },
                )
                self.assertEqual(
                    response.status_code,
                    400,
                    f"Expected rejection for prefix '{prefix}' ({reason})",
                )
                response_text = str(response.json()).lower()
                # Different invalid prefixes return different error messages
                self.assertTrue(
                    "prefix" in response_text and ("letters" in response_text or "underscores" in response_text),
                    f"Expected error message about prefix validation for '{prefix}' ({reason}), got: {response.json()}",
                )

    def test_create_external_data_source_accepts_valid_prefix(self):
        """Test that valid prefixes are accepted."""
        valid_prefixes = [
            "valid_prefix",
            "_starts_with_underscore",
            "CamelCase",
            "with123numbers",
            "a",
            "a_b",
        ]

        for prefix in valid_prefixes:
            with self.subTest(prefix=prefix):
                response = self.client.post(
                    f"/api/environments/{self.team.pk}/external_data_sources/",
                    data={
                        "source_type": "Stripe",
                        "prefix": prefix,
                        "payload": {
                            "stripe_secret_key": "sk_test_123",
                            "schemas": [
                                {
                                    "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                                    "should_sync": True,
                                    "sync_type": "full_refresh",
                                },
                            ],
                        },
                    },
                )
                self.assertIn(
                    response.status_code,
                    [200, 201],
                    f"Expected acceptance for valid prefix '{prefix}'",
                )
