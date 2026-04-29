import uuid
import typing as t
from typing import cast

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, FuzzyInt
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import override_settings

import psycopg
from parameterized import parameterized
from rest_framework import status

from posthog.schema import (
    SourceFieldFileUploadConfig,
    SourceFieldFileUploadJsonFormatConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceFieldSSHTunnelConfig,
    SourceFieldSwitchGroupConfig,
)

from posthog.models import Team
from posthog.models.project import Project
from posthog.temporal.data_imports.sources import SourceRegistry
from posthog.temporal.data_imports.sources.bigquery.bigquery import BigQuerySourceConfig
from posthog.temporal.data_imports.sources.common.base import FieldType
from posthog.temporal.data_imports.sources.common.schema import SourceSchema
from posthog.temporal.data_imports.sources.postgres.postgres import PostgresDiscoveredSchema
from posthog.temporal.data_imports.sources.postgres.source import PostgresSource
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

from products.data_warehouse.backend.api.external_data_source import (
    get_nonsensitive_and_sensitive_field_names,
    strip_sensitive_from_dict,
)
from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource
from products.data_warehouse.backend.models.external_data_job import ExternalDataJob
from products.data_warehouse.backend.models.external_data_schema import sync_frequency_interval_to_sync_frequency
from products.data_warehouse.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import IncrementalFieldType
from products.revenue_analytics.backend.joins import get_customer_revenue_view_name


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
                "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
            },
        )

    def _create_external_data_schema(self, source_id) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source_id, table=None
        )

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_delete_on_missing_schemas(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": False,
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_delete_on_bad_schema(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": "SomeOtherSchema", "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    @patch(
        "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas(self, _mock_workflow_exists):
        source = self._create_external_data_source()
        schema_one = ExternalDataSchema.objects.create(
            name="Customers",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        schema_two = ExternalDataSchema.objects.create(
            name="Invoices",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
            data={
                "schemas": [
                    {"id": str(schema_one.id), "should_sync": False},
                    {"id": str(schema_two.id), "should_sync": False},
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert {schema["id"]: schema["should_sync"] for schema in response.json()} == {
            str(schema_one.id): False,
            str(schema_two.id): False,
        }

        schema_one.refresh_from_db()
        schema_two.refresh_from_db()
        assert schema_one.should_sync is False
        assert schema_two.should_sync is False

    @patch(
        "products.data_warehouse.backend.api.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas_runs_deferred_temporal_updates(self, _mock_workflow_exists):
        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with patch(
            "products.data_warehouse.backend.api.external_data_schema.sync_external_data_job_workflow"
        ) as mock_sync_external_data_job_workflow:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
                data={"schemas": [{"id": str(schema.id), "sync_frequency": "7day"}]},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK

        schema.refresh_from_db()
        assert sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval) == "7day"
        assert mock_sync_external_data_job_workflow.call_count == 1
        assert mock_sync_external_data_job_workflow.call_args.kwargs == {"create": False, "should_sync": True}
        assert mock_sync_external_data_job_workflow.call_args.args[0].id == schema.id

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_prefix_external_data_source(self, _mock_validate):
        # Create no prefix

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_missing_field(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_missing_type(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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
        with (
            patch(
                "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas"
            ) as mocked_get_bigquery_schemas,
            patch(
                "posthog.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
                return_value=(True, None),
            ),
        ):
            mocked_get_bigquery_schemas.return_value = {"my_table": [("something", "DATE", False)]}

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

        # A cached instance setting lookup can shave off one query depending on test order.
        with self.assertNumQueries(FuzzyInt(24, 25)):
            response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 2)

    def test_connections_returns_lightweight_direct_connection_options(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="Primary database",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "password": "secret"},
            connection_metadata={"engine": "duckdb", "database": "ducklake", "available_functions": ["date_bin"]},
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "id": str(source.pk),
                    "prefix": "Primary database",
                    "engine": "duckdb",
                }
            ],
        )

    def test_dont_expose_job_inputs(self):
        self._create_external_data_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        payload = response.json()
        results = payload["results"]

        assert len(results) == 1

        result = results[0]
        # sensitive fields like stripe_secret_key should be stripped, but auth_method selection is kept
        assert result.get("job_inputs") == {"auth_method": {"selection": "api_key"}}

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_after_get_preserves_stripe_secret_key(self, _mock_validate):
        source = self._create_external_data_source()

        # GET strips stripe_secret_key from auth_method
        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert "stripe_secret_key" not in get_data["job_inputs"]["auth_method"]

        # PATCH with the sanitized data from GET (simulating user saving without changes)
        patch_response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": get_data["job_inputs"]},
        )
        assert patch_response.status_code == 200

        # stripe_secret_key must still be in the DB
        source.refresh_from_db()
        assert source.job_inputs["auth_method"]["stripe_secret_key"] == "sk_test_123"

    @patch(
        "posthog.temporal.data_imports.sources.snowflake.source.SnowflakeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_after_get_preserves_snowflake_keypair_private_key(self, _mock_validate):
        """Regression: Snowflake's keypair auth uses `auth_type` (not `auth_method`).
        After redaction, a PATCH that doesn't re-supply private_key must not wipe it.
        """
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Snowflake",
            created_by=self.user,
            prefix="snowflake-test",
            job_inputs={
                "account_id": "abc-123",
                "database": "MY_DB",
                "warehouse": "COMPUTE_WH",
                "schema": "PUBLIC",
                "auth_type": {
                    "selection": "keypair",
                    "user": "myuser",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----",
                    "passphrase": "secret-passphrase",
                },
            },
        )

        # GET strips private_key and passphrase from auth_type
        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        get_data = get_response.json()
        assert "private_key" not in get_data["job_inputs"]["auth_type"]
        assert "passphrase" not in get_data["job_inputs"]["auth_type"]
        assert get_data["job_inputs"]["auth_type"]["user"] == "myuser"

        # PATCH with the redacted data (simulating a save without re-pasting credentials)
        patch_response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": get_data["job_inputs"]},
        )
        assert patch_response.status_code == 200, patch_response.json()

        # Sensitive fields nested in auth_type must still be in the DB
        source.refresh_from_db()
        assert source.job_inputs["auth_type"]["selection"] == "keypair"
        assert source.job_inputs["auth_type"]["user"] == "myuser"
        assert source.job_inputs["auth_type"]["private_key"].startswith("-----BEGIN PRIVATE KEY-----")
        assert source.job_inputs["auth_type"]["passphrase"] == "secret-passphrase"

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_switching_auth_method_drops_old_secret_key(self, _mock_validate):
        source = self._create_external_data_source()

        # Switch from api_key to oauth — old stripe_secret_key should NOT carry over
        patch_response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"auth_method": {"selection": "oauth", "stripe_integration_id": "42"}}},
        )
        assert patch_response.status_code == 200

        source.refresh_from_db()
        assert source.job_inputs["auth_method"]["selection"] == "oauth"
        assert source.job_inputs["auth_method"]["stripe_integration_id"] == "42"
        # Old secret key must not carry over — config round-trip may include it as None (default)
        assert source.job_inputs["auth_method"].get("stripe_secret_key") is None

    def test_get_github_oauth_preserves_integration_id_strips_token(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Github",
            created_by=self.user,
            prefix="gh",
            job_inputs={
                "auth_method": {"selection": "oauth", "github_integration_id": "99"},
                "repository": "org/repo",
            },
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert response.status_code == 200
        auth_method = response.json()["job_inputs"]["auth_method"]
        assert auth_method == {"selection": "oauth", "github_integration_id": "99"}

    def test_get_github_pat_strips_token(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Github",
            created_by=self.user,
            prefix="gh",
            job_inputs={
                "auth_method": {"selection": "pat", "personal_access_token": "ghp_secret"},
                "repository": "org/repo",
            },
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert response.status_code == 200
        auth_method = response.json()["job_inputs"]["auth_method"]
        assert auth_method == {"selection": "pat"}
        assert "personal_access_token" not in auth_method

    def test_get_stripe_oauth_preserves_integration_id(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="st",
            job_inputs={
                "auth_method": {"selection": "oauth", "stripe_integration_id": "42"},
            },
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert response.status_code == 200
        auth_method = response.json()["job_inputs"]["auth_method"]
        assert auth_method == {"selection": "oauth", "stripe_integration_id": "42"}

    @patch(
        "posthog.temporal.data_imports.sources.github.source.GithubSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_after_get_preserves_github_pat(self, _mock_validate):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Github",
            created_by=self.user,
            prefix="gh",
            job_inputs={
                "auth_method": {"selection": "pat", "personal_access_token": "ghp_secret"},
                "repository": "org/repo",
            },
        )

        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        assert "personal_access_token" not in get_response.json()["job_inputs"]["auth_method"]

        patch_response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": get_response.json()["job_inputs"]},
        )
        assert patch_response.status_code == 200

        source.refresh_from_db()
        assert source.job_inputs["auth_method"]["personal_access_token"] == "ghp_secret"

    def test_update_with_malformed_auth_method_returns_400(self):
        source = self._create_external_data_source()

        patch_response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"auth_method": "invalid"}},
        )
        assert patch_response.status_code == 400

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
                "description",
                "access_method",
                "engine",
                "last_run_at",
                "schemas",
                "job_inputs",
                "revenue_analytics_config",
                "user_access_level",
                "supports_webhooks",
            ],
        )
        self.assertIsNone(payload["engine"])
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
                    "label": schema.label,
                    "latest_error": schema.latest_error,
                    "should_sync": schema.should_sync,
                    "status": schema.status,
                    "sync_type": schema.sync_type,
                    "table": schema.table,
                    "sync_frequency": sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval),
                    "sync_time_of_day": schema.sync_time_of_day,
                    "description": schema.description,
                    "primary_key_columns": None,
                    "cdc_table_mode": "consolidated",
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

    @patch("products.data_warehouse.backend.api.external_data_source.capture_exception")
    @patch(
        "products.data_warehouse.backend.api.external_data_source.delete_external_data_schedule",
        side_effect=Exception("External delete failed"),
    )
    def test_delete_external_data_source_soft_deletes_even_if_external_cleanup_fails(
        self, _mock_delete_schedule, mock_capture_exception
    ):
        source = self._create_external_data_source()
        table = DataWarehouseTable.objects.create(
            name="test_table",
            format=DataWarehouseTable.TableFormat.CSVWithNames,
            team=self.team,
            external_data_source=source,
            url_pattern="http://example.com/data/*.csv",
        )
        schema = ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source.pk, table=table
        )

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204
        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()
        assert ExternalDataSchema.objects.filter(pk=schema.pk, deleted=True).exists()
        assert DataWarehouseTable.raw_objects.filter(pk=table.pk, deleted=True).exists()
        assert mock_capture_exception.call_count == 2  # one for source, one for schema

    # TODO: update this test
    @patch("products.data_warehouse.backend.api.external_data_source.trigger_external_data_source_workflow")
    def test_reload_external_data_source(self, mock_trigger):
        source = self._create_external_data_source()

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/reload/")

        source.refresh_from_db()

        self.assertEqual(mock_trigger.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(source.status, "Running")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_creates_new_schemas_and_returns_counts(self, mock_get_source):
        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": "5432",
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "analytics",
        }
        mock_get_source.return_value.parse_config.return_value = parsed_config
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="table_a", supports_incremental=False, supports_append=False),
            SourceSchema(name="table_b", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["added"], 2)
        self.assertEqual(data["deleted"], 0)
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count(), 2
        )
        names = list(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        self.assertCountEqual(names, ["table_a", "table_b"])

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_creates_new_schemas_and_deletes_missing_schemas(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="new_table", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()
        ExternalDataSchema.objects.create(name="existing", team_id=self.team.pk, source_id=source.pk, should_sync=False)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["added"], 1)
        self.assertEqual(data["deleted"], 1)
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count(), 1
        )
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=True).count(), 1
        )
        names = list(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        self.assertCountEqual(names, ["new_table"])

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_adds_only_new_schemas(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="existing", supports_incremental=False, supports_append=False),
            SourceSchema(name="new_table", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()
        ExternalDataSchema.objects.create(name="existing", team_id=self.team.pk, source_id=source.pk, should_sync=False)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["added"], 1)
        self.assertEqual(data["deleted"], 0)
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count(), 2
        )
        self.assertTrue(
            ExternalDataSchema.objects.filter(
                team_id=self.team.pk, source_id=source.pk, name="new_table", deleted=False
            ).exists()
        )

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_idempotent_no_duplicates(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="only_one", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()

        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/")
        response2 = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.json()["added"], 0)
        self.assertEqual(
            ExternalDataSchema.objects.filter(
                team_id=self.team.pk, source_id=source.pk, name="only_one", deleted=False
            ).count(),
            1,
        )

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_restores_deleted_schema_instead_of_creating_duplicate(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="restored_table",
                supports_incremental=False,
                supports_append=False,
            ),
        ]
        source = self._create_external_data_source()
        # Simulate the realistic soft-delete path: the schema was syncing,
        # then got removed from the source which sets should_sync=False before
        # soft-deleting (see sync_old_schemas_with_new_schemas).
        deleted_schema = ExternalDataSchema.objects.create(
            name="restored_table",
            team_id=self.team.pk,
            source_id=source.pk,
            should_sync=False,
            deleted=True,
            sync_type_config={"legacy_key": "keep"},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["added"], 1)
        self.assertEqual(response.json()["deleted"], 0)
        self.assertEqual(
            ExternalDataSchema.objects.filter(
                team_id=self.team.pk, source_id=source.pk, name="restored_table", deleted=False
            ).count(),
            1,
        )
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, name="restored_table").count(),
            1,
        )

        restored_schema = ExternalDataSchema.objects.get(pk=deleted_schema.pk)
        self.assertFalse(restored_schema.deleted)
        # Restored schemas come back disabled — the user must opt in again
        self.assertFalse(restored_schema.should_sync)
        self.assertEqual(restored_schema.sync_type_config.get("legacy_key"), "keep")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_updates_labels_on_existing_schemas(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="c123", label="general", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="c123", team_id=self.team.pk, source_id=source.pk, should_sync=False
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        schema.refresh_from_db()
        self.assertEqual(schema.label, "general")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_updates_changed_label(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="c123", label="renamed-channel", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="c123", label="general", team_id=self.team.pk, source_id=source.pk, should_sync=False
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        schema.refresh_from_db()
        self.assertEqual(schema.label, "renamed-channel")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_sets_label_on_new_schema(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="c456", label="random", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="c456")
        self.assertEqual(schema.label, "random")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_sets_label_on_restored_deleted_schema(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="c789", label="announcements", supports_incremental=False, supports_append=False),
        ]
        source = self._create_external_data_source()
        deleted_schema = ExternalDataSchema.objects.create(
            name="c789", team_id=self.team.pk, source_id=source.pk, should_sync=False, deleted=True
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        deleted_schema.refresh_from_db()
        self.assertFalse(deleted_schema.deleted)
        self.assertEqual(deleted_schema.label, "announcements")

    def test_refresh_schemas_returns_400_when_no_job_inputs(self):
        source = self._create_external_data_source()
        source.job_inputs = None
        source.save()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("configuration", response.json().get("message", ""))

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_returns_400_when_get_schemas_raises(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.side_effect = Exception("Connection failed")
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not fetch schemas from source", response.json().get("message", ""))

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    @patch("products.data_warehouse.backend.api.external_data_source.trigger_external_data_source_workflow")
    def test_reload_direct_external_data_source_refreshes_schemas(self, mock_trigger, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="table_a",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("user_id", "integer", False)],
                foreign_keys=[("user_id", "posthog_user", "id")],
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/reload/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_trigger.call_count, 0)
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count(), 1
        )
        self.assertEqual(
            DataWarehouseTable.objects.filter(
                team_id=self.team.pk,
                external_data_source=source,
                deleted=False,
                name="table_a",
            ).count(),
            0,
        )
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="table_a")
        self.assertFalse(schema.should_sync)
        self.assertIsNone(schema.table)
        self.assertEqual(
            schema.sync_type_config.get("schema_metadata", {}).get("foreign_keys"),
            [{"column": "user_id", "target_table": "posthog_user", "target_column": "id"}],
        )

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_soft_deletes_live_tables_for_deleted_schemas(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = []
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )

        table = DataWarehouseTable.objects.create(
            name="legacy_table",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns=[],
        )
        stale_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="legacy_table",
            table=table,
            deleted=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(DataWarehouseTable.raw_objects.filter(pk=table.pk, deleted=True).exists())
        self.assertTrue(ExternalDataSchema.objects.filter(pk=stale_schema.pk, deleted=True).exists())

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_keeps_disabled_schema_table_deleted(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="Accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            )
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )

        table = DataWarehouseTable.objects.create(
            name="Accounts",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="Accounts",
            should_sync=False,
            table=table,
            sync_type_config={"schema_metadata": {"columns": [], "foreign_keys": []}},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schema.refresh_from_db()
        self.assertFalse(schema.should_sync)
        self.assertTrue(DataWarehouseTable.raw_objects.get(pk=table.pk).deleted)
        self.assertEqual(schema.sync_type_config["schema_metadata"]["columns"][0]["name"], "id")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_new_schema_is_opt_in(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="Accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            )
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="Accounts")
        self.assertFalse(schema.should_sync)
        self.assertIsNone(schema.table)

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_preserves_disabled_schema_when_it_reappears(self, mock_get_source):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="Accounts",
            should_sync=False,
            sync_type_config={"schema_metadata": {"columns": [], "foreign_keys": []}},
        )

        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = []
        first_response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        schema.refresh_from_db()
        self.assertTrue(schema.deleted)

        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="Accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            )
        ]
        second_response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        schema.refresh_from_db()
        self.assertFalse(schema.deleted)
        self.assertFalse(schema.should_sync)
        self.assertIsNone(schema.table)

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_preserves_enabled_schema_when_it_reappears(self, mock_get_source):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
        )
        schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="Accounts",
            should_sync=True,
            deleted=True,
            sync_type_config={"schema_metadata": {"columns": [], "foreign_keys": []}},
        )

        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="Accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            )
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        schema.refresh_from_db()
        self.assertFalse(schema.deleted)
        self.assertTrue(schema.should_sync)
        table = schema.table
        assert table is not None
        self.assertEqual(table.name, "Accounts")

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_direct_postgres_updates_connection_metadata(self, mock_get_source):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432},
            connection_metadata={"database": "old_db", "available_functions": ["count"]},
        )

        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_connection_metadata.return_value = {
            "database": "ducklake",
            "version": "PostgreSQL 15.0 (Duckgres/DuckDB)",
            "engine": "duckdb",
            "function_source": "duckdb_functions",
            "available_functions": ["duckdb_functions", "date_bin"],
        }
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="Accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            )
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        source.refresh_from_db()
        connection_metadata = source.connection_metadata
        assert connection_metadata is not None
        self.assertEqual(connection_metadata["database"], "ducklake")
        self.assertEqual(connection_metadata["available_functions"], ["duckdb_functions", "date_bin"])

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_direct_postgres_preserves_numeric_as_decimal(self, mock_get_source):
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "public",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_connection_metadata.return_value = {
            "database": "app",
            "version": "Duckgres/DuckDB",
            "engine": "duckdb",
            "function_source": "duckdb_functions",
            "available_functions": ["duckdb_functions", "date_bin"],
        }
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("amount", "numeric", False)],
                foreign_keys=[],
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "direct",
                "prefix": "Primary database",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "schemas": [{"name": "accounts", "should_sync": True, "sync_type": None}],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source__id=response.json()["id"], name="accounts")
        table = schema.table
        assert table is not None
        assert schema.sync_type_config is not None
        assert table.columns is not None
        self.assertEqual(schema.sync_type_config["schema_metadata"]["columns"][0]["data_type"], "numeric")
        self.assertEqual(table.columns["amount"]["clickhouse"], "Decimal")
        self.assertEqual(table.columns["amount"]["hogql"], "numeric")
        source = ExternalDataSource.objects.get(pk=response.json()["id"])
        connection_metadata = source.connection_metadata
        assert connection_metadata is not None
        self.assertEqual(connection_metadata["database"], "app")
        self.assertEqual(connection_metadata["available_functions"], ["duckdb_functions", "date_bin"])

    def test_create_direct_postgres_requires_name(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "direct",
                "prefix": "   ",
                "payload": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"message": "Name is required for direct query sources"})

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_direct_postgres_does_not_require_prefix_namespace(self, mock_get_source):
        ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix=None,
        )

        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "public",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "direct",
                "prefix": "Read replica",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "schemas": [{"name": "accounts", "should_sync": True, "sync_type": None}],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_direct_postgres_creates_only_selected_tables(self, mock_get_source):
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "public",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            ),
            SourceSchema(
                name="payments",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "direct",
                "prefix": "Primary database",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "schemas": [
                        {"name": "accounts", "should_sync": True, "sync_type": None},
                        {"name": "payments", "should_sync": False, "sync_type": None},
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        source = ExternalDataSource.objects.get(id=response.json()["id"])

        self.assertEqual(source.prefix, "Primary database")

        accounts_schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="accounts")
        payments_schema = ExternalDataSchema.objects.get(team_id=self.team.pk, source_id=source.pk, name="payments")

        self.assertTrue(accounts_schema.should_sync)
        self.assertFalse(payments_schema.should_sync)
        self.assertIsNotNone(accounts_schema.table)
        self.assertIsNone(payments_schema.table)

        self.assertEqual(
            DataWarehouseTable.objects.filter(
                team_id=self.team.pk,
                external_data_source=source,
                deleted=False,
                name="accounts",
            ).count(),
            1,
        )

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_direct_postgres_blank_schema_prefixes_table_names_and_preserves_physical_schema(
        self, mock_get_source
    ):
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="public.accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="accounts",
            ),
            SourceSchema(
                name="analytics.accounts",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="analytics",
                source_table_name="accounts",
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "direct",
                "prefix": "Primary database",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "",
                    "schemas": [
                        {"name": "public.accounts", "should_sync": True, "sync_type": None},
                        {"name": "analytics.accounts", "should_sync": True, "sync_type": None},
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        source = ExternalDataSource.objects.get(id=response.json()["id"])

        public_schema = ExternalDataSchema.objects.get(
            team_id=self.team.pk, source_id=source.pk, name="public.accounts"
        )
        analytics_schema = ExternalDataSchema.objects.get(
            team_id=self.team.pk, source_id=source.pk, name="analytics.accounts"
        )
        assert public_schema.table is not None
        assert analytics_schema.table is not None

        self.assertEqual(public_schema.table.name, "public.accounts")
        self.assertEqual(public_schema.table.options["direct_postgres_schema"], "public")
        self.assertEqual(public_schema.table.options["direct_postgres_table"], "accounts")
        self.assertEqual(analytics_schema.table.name, "analytics.accounts")
        self.assertEqual(analytics_schema.table.options["direct_postgres_schema"], "analytics")
        self.assertEqual(analytics_schema.table.options["direct_postgres_table"], "accounts")
        self.assertEqual(public_schema.sync_type_config["schema_metadata"]["source_schema"], "public")
        self.assertEqual(analytics_schema.sync_type_config["schema_metadata"]["source_schema"], "analytics")

    @patch("products.data_warehouse.backend.api.external_data_source.is_cdc_enabled_for_team", return_value=True)
    @patch(
        "products.data_warehouse.backend.api.external_data_source.ExternalDataSourceViewSet._add_table_to_cdc_publication"
    )
    @patch("products.data_warehouse.backend.api.external_data_source.ExternalDataSourceViewSet._setup_cdc_slot")
    @patch("posthog.temporal.data_imports.sources.postgres.postgres.get_primary_key_columns")
    @patch("posthog.temporal.data_imports.sources.postgres.cdc.slot_manager.cdc_pg_connection")
    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_cdc_with_blank_schema_uses_physical_schema_metadata(
        self,
        mock_get_source,
        mock_cdc_pg_connection,
        mock_get_primary_key_columns,
        mock_setup_cdc_slot,
        mock_add_table_to_cdc_publication,
        _mock_is_cdc_enabled_for_team,
    ):
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.schema = ""
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="analytics.events",
                supports_incremental=False,
                supports_append=False,
                supports_cdc=True,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="analytics",
                source_table_name="events",
            )
        ]

        mock_cdc_pg_connection.return_value.__enter__.return_value = object()
        mock_cdc_pg_connection.return_value.__exit__.return_value = None
        mock_get_primary_key_columns.return_value = {"events": ["id"]}

        def setup_cdc_slot(_source_impl, _source_config, source_model, _payload):
            source_model.job_inputs = {
                **(source_model.job_inputs or {}),
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            }
            source_model.save(update_fields=["job_inputs", "updated_at"])
            return None

        mock_setup_cdc_slot.side_effect = setup_cdc_slot

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "",
                    "cdc_enabled": True,
                    "schemas": [
                        {"name": "analytics.events", "should_sync": True, "sync_type": "cdc"},
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, name="analytics.events")
        assert schema.sync_type_config["primary_key_columns"] == ["id"]

        mock_get_primary_key_columns.assert_called_once()
        assert mock_get_primary_key_columns.call_args.args[1] == "analytics"
        assert mock_get_primary_key_columns.call_args.args[2] == ["events"]

        mock_add_table_to_cdc_publication.assert_called_once()
        assert mock_add_table_to_cdc_publication.call_args.args[1:] == ("test_pub", "analytics", "events")

    @parameterized.expand(
        [
            # Frontend sends null when the user leaves the PK selector empty — backend falls
            # back to the source-detected primary key so sync-time detection is not the only
            # line of defense.
            ("fallback_to_detected", None, ["id"], ["id"]),
            # User explicitly overrides — caller value wins, detected is ignored.
            ("explicit_wins_over_detected", ["custom_pk"], ["id"], ["custom_pk"]),
            # Nothing detected and nothing provided — key omitted from sync_type_config
            # entirely (preserves pre-existing behaviour for tables without a PK).
            ("both_absent_omits_key", None, None, None),
        ]
    )
    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_incremental_primary_key_fallback(
        self,
        _name: str,
        payload_primary_keys: list[str] | None,
        detected_primary_keys: list[str] | None,
        expected_persisted: list[str] | None,
        mock_get_source,
    ):
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.schema = "public"
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "public",
        }
        source_mock.parse_config.return_value = parsed_config
        source_mock.validate_credentials.return_value = (True, None)
        source_mock.get_schemas.return_value = [
            SourceSchema(
                name="events",
                supports_incremental=True,
                supports_append=True,
                columns=[("id", "integer", False), ("updated_at", "timestamp", False)],
                foreign_keys=[],
                incremental_fields=[
                    {
                        "label": "updated_at",
                        "type": IncrementalFieldType.Timestamp,
                        "field": "updated_at",
                        "field_type": IncrementalFieldType.Timestamp,
                        "nullable": False,
                    }
                ],
                detected_primary_keys=detected_primary_keys,
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "schemas": [
                        {
                            "name": "events",
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "updated_at",
                            "incremental_field_type": "timestamp",
                            "primary_key_columns": payload_primary_keys,
                        },
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, name="events")
        if expected_persisted is None:
            assert "primary_key_columns" not in schema.sync_type_config
        else:
            assert schema.sync_type_config["primary_key_columns"] == expected_persisted

    def test_create_direct_non_postgres_is_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "access_method": "direct",
                "prefix": "Read replica",
                "payload": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"message": "Direct query mode is currently supported only for Postgres sources."},
        )

    def test_source_prefix_rejects_direct_non_postgres(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/source_prefix/",
            data={
                "source_type": "Stripe",
                "access_method": "direct",
                "prefix": "Read replica",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"message": "Direct query mode is currently supported only for Postgres sources."},
        )

    def test_create_postgres_warehouse_source_requires_schema(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "access_method": "warehouse",
                "payload": {
                    "host": "db.example.com",
                    "port": 5432,
                    "database": "postgres",
                    "user": "postgres",
                    "password": "secret",
                    "schema": "",
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"message": "Schema is required for warehouse imports."})

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_database_schema_postgres_direct_allows_blank_schema(self, mock_get_source):
        source = PostgresSource()
        mock_get_source.return_value = source

        with (
            patch.object(source, "validate_credentials_for_access_method", return_value=(True, None)) as validate,
            patch.object(
                source,
                "get_schemas",
                return_value=[
                    SourceSchema(
                        name="public.accounts",
                        supports_incremental=False,
                        supports_append=False,
                        columns=[("id", "integer", False)],
                        foreign_keys=[],
                    )
                ],
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Postgres",
                    "access_method": "direct",
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["table"], "public.accounts")
        validate.assert_called_once()
        self.assertEqual(validate.call_args.args[2], "direct")

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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "blah"},
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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "invalid_key"},
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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "invalid_key"},
                },
            )

            assert response.status_code == 400
            assert "Stripe credentials lack permissions for Account, Invoice" in response.json()["message"]

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
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "stripe_account_id": "blah",
                },
            )
            results = response.json()

            self.assertEqual(response.status_code, 200)

            table_names = [table["table"] for table in results]
            for table in STRIPE_ENDPOINTS:
                assert table in table_names

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_database_schema_does_not_request_row_counts(self, mock_get_source):
        parsed_config = Mock()
        mock_source = mock_get_source.return_value
        mock_source.validate_config.return_value = (True, [])
        mock_source.parse_config.return_value = parsed_config
        mock_source.validate_credentials.return_value = (True, None)
        mock_source.get_schemas.return_value = [
            SourceSchema(name="table_1", supports_incremental=False, supports_append=False, row_count=42)
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
            data={
                "source_type": "Stripe",
                "api_key": "test",
            },
        )

        self.assertEqual(response.status_code, 200)
        mock_source.get_schemas.assert_called_once_with(parsed_config, self.team.pk)

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
        return_value={
            "table_1": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="table_1",
                columns=[("id", "integer", True)],
            )
        },
    )
    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
        return_value={},
    )
    @patch("posthog.temporal.data_imports.sources.postgres.source.get_primary_key_columns", return_value={})
    @patch("posthog.temporal.data_imports.sources.postgres.source.pg_connection")
    @patch("posthog.temporal.data_imports.sources.postgres.source.get_postgres_row_count")
    def test_internal_postgres(
        self,
        patch_get_postgres_row_count,
        patch_pg_connection,
        _patch_get_primary_key_columns,
        _patch_get_postgres_foreign_keys,
        patch_get_sql_schemas_for_source_type,
    ):
        patch_pg_connection.return_value.__enter__.return_value = object()
        patch_pg_connection.return_value.__exit__.return_value = None

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
                    "label": None,
                    "should_sync": False,
                    "should_sync_default": True,
                    "description": None,
                    "rows": None,
                    "incremental_fields": [
                        {"label": "id", "type": "integer", "field": "id", "field_type": "integer", "nullable": True}
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "cdc_available": None,
                    "incremental_field": "id",
                    "sync_type": None,
                    "supports_webhooks": False,
                    "available_columns": [
                        {"field": "id", "label": "id", "type": "integer", "nullable": True},
                    ],
                    "detected_primary_keys": ["id"],
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
                    "label": None,
                    "should_sync": False,
                    "should_sync_default": True,
                    "description": None,
                    "rows": None,
                    "incremental_fields": [
                        {"label": "id", "type": "integer", "field": "id", "field_type": "integer", "nullable": True}
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "cdc_available": None,
                    "incremental_field": "id",
                    "sync_type": None,
                    "supports_webhooks": False,
                    "available_columns": [
                        {"field": "id", "label": "id", "type": "integer", "nullable": True},
                    ],
                    "detected_primary_keys": ["id"],
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

        patch_get_postgres_row_count.assert_not_called()

    @parameterized.expand(
        [
            ("192.168.1.1",),
            ("169.254.169.254",),
            ("localhost",),
            ("127.0.0.1",),
            ("0.0.0.0",),
        ]
    )
    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
        return_value={
            "table_1": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="table_1",
                columns=[("id", "integer", True)],
            )
        },
    )
    def test_blocks_internal_host(self, host, _patch_schemas):
        database_schema_url = f"/api/environments/{self.team.pk}/external_data_sources/database_schema/"
        database_schema_data = {
            "source_type": "Postgres",
            "host": host,
            "port": int(settings.PG_PORT),
            "database": settings.PG_DATABASE,
            "user": settings.PG_USER,
            "password": settings.PG_PASSWORD,
            "schema": "public",
        }
        create_url = f"/api/environments/{self.team.pk}/external_data_sources/"
        create_data = {
            "source_type": "Postgres",
            "payload": {
                "host": host,
                "port": 5432,
                "database": "mydb",
                "user": "user",
                "password": "pass",
                "schema": "public",
            },
            "schemas": [],
        }
        with override_settings(CLOUD_DEPLOYMENT="US"):
            for url, data in [(database_schema_url, database_schema_data), (create_url, create_data)]:
                response = self.client.post(url, data=data)
                self.assertEqual(response.status_code, 400, f"Expected 400 for {host} on {url}")
                self.assertEqual(response.json(), {"message": "Hosts with internal IP addresses are not allowed"})

            self.assertFalse(
                ExternalDataSource.objects.filter(team=self.team, source_type="Postgres").exists(),
            )

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

    @parameterized.expand(
        [
            ("single_schema", "?schemas=Customers", 1),
            ("multiple_schemas", "?schemas=Customers&schemas=Invoices", 2),
            ("no_filter", "", 2),
        ]
    )
    def test_source_jobs_schema_filter(self, _name, query_string, expected_count):
        source = self._create_external_data_source()
        schema1 = ExternalDataSchema.objects.create(
            name="Customers", team_id=self.team.pk, source_id=source.pk, table=None
        )
        schema2 = ExternalDataSchema.objects.create(
            name="Invoices", team_id=self.team.pk, source_id=source.pk, table=None
        )
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema1,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=100,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=source,
            schema=schema2,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=200,
            pipeline_version=ExternalDataJob.PipelineVersion.V1,
        )

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/jobs{query_string}",
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == expected_count

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_trimming_payload(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "  sk_test_123   "},
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

        assert source.job_inputs["auth_method"]["stripe_secret_key"] == "  sk_test_123   "
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
        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ) as mock_validate_credentials:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
                data={
                    "job_inputs": {
                        "ssh_tunnel": {
                            "enabled": True,
                            "host": "ssh.example.com",
                            "port": 22,
                            "auth_type": {
                                "selection": "password",
                                "username": "testuser",
                                "password": "testpass",
                                "passphrase": "testphrase",
                                "private_key": "testkey",
                            },
                        }
                    },
                },
            )
        mock_validate_credentials.assert_called_once()

        assert response.status_code == 200

        # Verify the SSH tunnel config was normalized correctly
        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["enabled"] == "True"
        assert source.job_inputs["ssh_tunnel"]["host"] == "ssh.example.com"
        assert source.job_inputs["ssh_tunnel"]["port"] == "22"
        assert source.job_inputs["ssh_tunnel"]["auth"]["type"] == "password"
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
        assert ssh_tunnel["auth"]["selection"] == "password"
        assert ssh_tunnel["auth"]["username"] == "testuser"
        # Sensitive fields should not be included in response (to prevent them being echoed back)
        assert "password" not in ssh_tunnel["auth"]
        assert "passphrase" not in ssh_tunnel["auth"]
        assert "private_key" not in ssh_tunnel["auth"]

    def test_update_after_get_preserves_ssh_tunnel_credentials(self):
        """
        Regression test for P0 bug: updating a source after viewing it should preserve credentials.

        The bug flow was:
        1. User creates source with SSH tunnel credentials
        2. User GETs source - API returns ssh_tunnel.auth with password=null (masked for security)
        3. User updates any field - frontend sends back the response including password=null
        4. Backend merges null over stored password - credentials lost
        5. Validation fails: "Required field 'auth' is missing"

        Fix: Don't include sensitive fields (password, passphrase, private_key) in API response at all.
        """
        # Create a source with SSH tunnel and credentials
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_creds",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "True",
                    "host": "ssh.example.com",
                    "port": "22",
                    "auth": {
                        "type": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                        "passphrase": None,
                        "private_key": None,
                    },
                },
            },
        )

        # Step 1: GET the source (simulating user opening the config page)
        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        get_data = get_response.json()

        # Step 2: PATCH with the exact data from GET (simulating user saving without changes)
        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ) as mock_validate_credentials:
            patch_response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={"job_inputs": get_data["job_inputs"]},
            )

        # Should succeed, not fail with "Required field 'auth' is missing"
        assert patch_response.status_code == 200, (
            f"Expected 200, got {patch_response.status_code}: {patch_response.json()}"
        )

        # Verify credentials are still intact
        source.refresh_from_db()
        assert source.job_inputs["password"] == "db_password"  # Main DB password preserved
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"  # SSH password preserved
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_null_password_preserves_existing(self, mock_validate_credentials):
        """Regression test: sending password=null should not overwrite stored password."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_null_pw",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        # Send update with password explicitly set to null (simulating frontend behavior)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "new-host.example.com",
                    "password": None,  # Frontend sends null
                },
            },
        )

        assert response.status_code == 200

        # Verify password was preserved, not overwritten with null
        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"  # Host was updated
        assert source.job_inputs["password"] == "original_password"  # Password preserved
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_empty_string_password_preserves_existing(self, mock_validate_credentials):
        """Regression test: sending password="" (empty string) should not overwrite stored password.

        This reproduces the bug where the frontend form sends an empty string for password
        when the user doesn't enter a new value, causing the stored password to be lost.
        """
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_empty_pw",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        # Send update with password as empty string (simulating frontend form behavior)
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "new-host.example.com",
                    "password": "",  # Frontend sends empty string when user doesn't enter new password
                },
            },
        )

        assert response.status_code == 200

        # Verify password was preserved, not overwritten with empty string
        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"  # Host was updated
        assert source.job_inputs["password"] == "original_password"  # Password preserved
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_new_password_updates_password(self, mock_validate_credentials):
        """Test that explicitly providing a new password does update it."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_new_pw",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        # Send update with a new password value
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "password": "new_password",
                },
            },
        )

        assert response.status_code == 200

        # Verify password was actually updated
        source.refresh_from_db()
        assert source.job_inputs["password"] == "new_password"
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_host_change_revalidates_credentials(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_host_only",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "new-host.example.com",
                },
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_non_host_job_input_change_revalidates_credentials(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_database_change",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "database": "renamed_db",
                },
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["database"] == "renamed_db"
        mock_validate_credentials.assert_called_once()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_without_job_inputs_does_not_revalidate_credentials(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_no_job_input_change",
            description="before",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "description": "after",
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.description == "after"
        mock_validate_credentials.assert_not_called()

    @patch(
        "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_source_without_ssh_tunnel_does_not_crash(self, mock_validate_credentials):
        """Regression test: updating a source that has no ssh_tunnel should not crash."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_no_ssh",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
                # No ssh_tunnel key at all
            },
        )

        # Update without providing ssh_tunnel
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "new-host.example.com",
                },
            },
        )

        # Should not crash with AttributeError: 'NoneType' object has no attribute 'setdefault'
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"

        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"
        assert source.job_inputs["password"] == "original_password"
        mock_validate_credentials.assert_called_once()

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_update_blocks_internal_host(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_internal_host",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "original_password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "localhost",
                },
            },
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Hosts with internal IP addresses are not allowed"

        source.refresh_from_db()
        assert source.job_inputs["host"] == "db.example.com"

    def test_update_direct_postgres_prefix(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
            prefix="Original name",
            job_inputs={
                "host": "172.16.0.0",
                "port": "123",
                "database": "database",
                "user": "user",
                "password": "password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
            data={"prefix": " Updated name "},
        )

        assert response.status_code == 200, response.content
        source.refresh_from_db()
        assert source.prefix == "Updated name"

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_update_direct_postgres_schema_filter_refreshes_existing_schemas(self, mock_get_source):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
            prefix="Direct source",
            job_inputs={
                "host": "localhost",
                "port": "5432",
                "database": "database",
                "user": "user",
                "password": "password",
            },
        )
        matching_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="analytics.events",
            should_sync=False,
            sync_type_config={"schema_metadata": {"columns": [], "foreign_keys": []}},
        )
        filtered_out_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="public.users",
            should_sync=True,
            sync_type_config={"schema_metadata": {"columns": [], "foreign_keys": []}},
        )

        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": "5432",
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "analytics",
        }
        mock_get_source.return_value.parse_config.return_value = parsed_config
        mock_get_source.return_value.validate_config.return_value = (True, [])
        mock_get_source.return_value.validate_credentials.return_value = (True, None)
        mock_get_source.return_value.get_connection_metadata.return_value = {"database": "ducklake", "engine": "duckdb"}
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="analytics.events",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="analytics",
                source_table_name="events",
            )
        ]

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "schema": "analytics",
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        matching_schema.refresh_from_db()
        filtered_out_schema.refresh_from_db()

        assert source.job_inputs["schema"] == "analytics"
        assert [schema["name"] for schema in response.json()["schemas"]] == ["analytics.events"]
        assert matching_schema.deleted is False
        assert matching_schema.sync_type_config["schema_metadata"]["source_schema"] == "analytics"
        assert filtered_out_schema.deleted is True

    @patch("products.data_warehouse.backend.api.external_data_source.SourceRegistry.get_source")
    def test_update_direct_postgres_schema_filter_preserves_selected_table_for_same_physical_schema(
        self, mock_get_source
    ):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
            prefix="Direct source",
            job_inputs={
                "host": "localhost",
                "port": "5432",
                "database": "database",
                "user": "user",
                "password": "password",
            },
        )
        table = DataWarehouseTable.objects.create(
            name="posthog.events",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"clickhouse": "Int32", "hogql": "integer", "valid": True}},
            options={
                "direct_postgres_schema": "posthog",
                "direct_postgres_table": "events",
            },
        )
        existing_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="posthog.events",
            should_sync=True,
            table=table,
            sync_type_config={
                "schema_metadata": {
                    "columns": [],
                    "foreign_keys": [],
                    "source_schema": "posthog",
                    "source_table_name": "events",
                }
            },
        )
        source_join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="posthog.events",
            source_table_key="id",
            joining_table_name="persons",
            joining_table_key="id",
            field_name="persons",
        )
        joining_join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="id",
            joining_table_name="posthog.events",
            joining_table_key="id",
            field_name="posthog_events",
        )

        parsed_config = Mock()
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": "5432",
            "database": "database",
            "user": "user",
            "password": "password",
            "schema": "posthog",
        }
        mock_get_source.return_value.parse_config.return_value = parsed_config
        mock_get_source.return_value.validate_config.return_value = (True, [])
        mock_get_source.return_value.validate_credentials.return_value = (True, None)
        mock_get_source.return_value.get_connection_metadata.return_value = {
            "database": "database",
            "engine": "postgres",
        }
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="events",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="posthog",
                source_table_name="events",
            )
        ]

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "schema": "posthog",
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        existing_schema.refresh_from_db()
        table.refresh_from_db()
        source_join.refresh_from_db()
        joining_join.refresh_from_db()

        assert source.job_inputs["schema"] == "posthog"
        assert existing_schema.name == "events"
        assert existing_schema.should_sync is True
        assert existing_schema.deleted is False
        assert existing_schema.table_id == table.id
        assert table.deleted is False
        assert table.name == "events"
        assert table.options["direct_postgres_schema"] == "posthog"
        assert table.options["direct_postgres_table"] == "events"
        assert [schema["name"] for schema in response.json()["schemas"]] == ["events"]
        assert ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count() == 1
        assert source_join.source_table_name == "events"
        assert joining_join.joining_table_name == "events"

    def test_update_source_cannot_change_access_method(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            created_by=self.user,
            prefix="Original name",
            job_inputs={
                "host": "172.16.0.0",
                "port": "123",
                "database": "database",
                "user": "user",
                "password": "password",
                "schema": "public",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
            data={"prefix": " Updated name ", "access_method": ExternalDataSource.AccessMethod.WAREHOUSE},
        )

        assert response.status_code == 400, response.content
        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Access method cannot be changed. Create a new source instead.",
            "type": "validation_error",
        }
        source.refresh_from_db()
        assert source.access_method == ExternalDataSource.AccessMethod.DIRECT
        assert source.prefix == "Original name"

    def test_update_source_with_ssh_tunnel_missing_auth(self):
        """Regression test: PATCH with ssh_tunnel but no auth key should not fail validation."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_no_auth",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "True",
                    "host": "ssh.example.com",
                    "port": "22",
                    "auth": {
                        "type": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                        "passphrase": None,
                        "private_key": None,
                    },
                },
            },
        )

        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={
                    "job_inputs": {
                        "ssh_tunnel": {
                            "enabled": False,
                        },
                    },
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"

        source.refresh_from_db()
        assert source.job_inputs["password"] == "db_password"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"

    def test_update_source_with_ssh_tunnel_missing_auth_surfaces_validation_failure(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_no_auth_error",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "True",
                    "host": "ssh.example.com",
                    "port": "22",
                    "auth": {
                        "type": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                        "passphrase": None,
                        "private_key": None,
                    },
                },
            },
        )

        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(False, "Mocked credentials failure"),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={
                    "job_inputs": {
                        "ssh_tunnel": {
                            "enabled": False,
                        },
                    },
                },
            )

        assert response.status_code == 400, response.json()
        assert response.json() == {
            "attr": None,
            "code": "invalid_input",
            "detail": "Mocked credentials failure",
            "type": "validation_error",
        }

        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["enabled"] == "True"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"

    def test_update_source_with_ssh_tunnel_enabled_missing_auth(self):
        """Regression test: PATCH with ssh_tunnel enabled but no auth key should preserve existing auth."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_enabled_no_auth",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "True",
                    "host": "ssh.example.com",
                    "port": "22",
                    "auth": {
                        "type": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                        "passphrase": None,
                        "private_key": None,
                    },
                },
            },
        )

        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={
                    "job_inputs": {
                        "ssh_tunnel": {
                            "enabled": True,
                            "host": "new-ssh.example.com",
                            "port": 22,
                        },
                    },
                },
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"

        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["host"] == "new-ssh.example.com"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"
        assert source.job_inputs["ssh_tunnel"]["auth"]["username"] == "sshuser"

    def test_update_legacy_auth_type_format_preserves_credentials(self):
        """
        Regression test for sources created via migration 0807 that use 'auth_type' instead of 'auth'.

        Migration 0807 stored SSH tunnel auth as 'auth_type' (the alias), but newer code stores
        it as 'auth' (the field name). The update flow must handle both formats to preserve
        credentials for migrated sources.
        """
        # Create a source with legacy 'auth_type' format (as created by migration 0807)
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_legacy_auth",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "True",
                    "host": "ssh.example.com",
                    "port": "22",
                    # Legacy format: 'auth_type' instead of 'auth'
                    "auth_type": {
                        "selection": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                        "passphrase": "",
                        "private_key": "",
                    },
                },
            },
        )

        # Step 1: GET the source - should properly read auth_type and return as auth
        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        get_data = get_response.json()

        # Verify the GET response has the auth data (read from auth_type)
        assert get_data["job_inputs"]["ssh_tunnel"]["auth"]["selection"] == "password"
        assert get_data["job_inputs"]["ssh_tunnel"]["auth"]["username"] == "sshuser"

        # Step 2: PATCH with the exact data from GET
        with patch(
            "posthog.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ):
            patch_response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={"job_inputs": get_data["job_inputs"]},
            )

        # Should succeed, not fail with validation error
        assert patch_response.status_code == 200, (
            f"Expected 200, got {patch_response.status_code}: {patch_response.json()}"
        )

        # Verify credentials are preserved
        source.refresh_from_db()
        assert source.job_inputs["password"] == "db_password"  # Main DB password preserved
        # After update, it should be normalized to 'auth' format
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"  # SSH password preserved

    def test_snowflake_auth_type_create_and_update(self):
        """Test that we can create and update the auth type for a Snowflake source"""
        with patch(
            "posthog.temporal.data_imports.sources.snowflake.source.get_snowflake_schemas"
        ) as mocked_get_snowflake_schemas:
            mocked_get_snowflake_schemas.return_value = {"my_table": [("something", "DATE", False)]}

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
        with patch(
            "posthog.temporal.data_imports.sources.snowflake.source.SnowflakeSource.validate_credentials",
            return_value=(True, None),
        ) as mock_validate_credentials:
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
        mock_validate_credentials.assert_called_once()

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
        with (
            patch(
                "posthog.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
                return_value=(True, None),
            ),
            patch(
                "posthog.temporal.data_imports.sources.bigquery.source.get_bigquery_schemas"
            ) as mocked_get_bigquery_schemas,
        ):
            mocked_get_bigquery_schemas.return_value = {"my_table": [("something", "DATE", False)]}

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
                        "use_custom_region": {"enabled": False, "region": ""},
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
        assert bq_config.use_custom_region is not None
        assert bq_config.use_custom_region.enabled is False
        assert bq_config.temporary_dataset is not None
        assert bq_config.temporary_dataset.enabled is False
        assert bq_config.temporary_dataset.temporary_dataset_id == ""

        # # Update the source by adding a temporary dataset
        with patch(
            "posthog.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
            return_value=(True, None),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
                data={
                    "job_inputs": {
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "dataset_id": "dummy_dataset_id",
                        "project_id": "dummy_project_id",
                        "region": "",
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
        assert bq_config.use_custom_region is not None
        assert bq_config.use_custom_region.enabled is False
        assert bq_config.temporary_dataset is not None
        assert bq_config.temporary_dataset.enabled is True
        assert bq_config.temporary_dataset.temporary_dataset_id == "dummy_temporary_dataset_id"

        # # Update the source by adding dataset project id
        with patch(
            "posthog.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
            return_value=(True, None),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source_model.pk}/",
                data={
                    "job_inputs": {
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "dataset_id": "dummy_dataset_id",
                        "project_id": "dummy_project_id",
                        "region": "",
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
        assert bq_config.use_custom_region is not None
        assert bq_config.use_custom_region.enabled is False
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

    def test_enabling_revenue_analytics_creates_person_join(self):
        source = self._create_external_data_source()
        source.revenue_analytics_config_safe.enabled = False
        source.revenue_analytics_config_safe.save()

        self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/revenue_analytics_config/",
            data={"enabled": True},
        )

        view_name = get_customer_revenue_view_name(source.prefix)
        assert DataWarehouseJoin.objects.filter(
            team=self.team,
            source_table_name=view_name,
            joining_table_name="persons",
            field_name="persons",
            deleted=False,
        ).exists()

    def test_disabling_revenue_analytics_removes_person_join(self):
        source = self._create_external_data_source()

        self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/revenue_analytics_config/",
            data={"enabled": True},
        )

        view_name = get_customer_revenue_view_name(source.prefix)
        assert DataWarehouseJoin.objects.filter(team=self.team, source_table_name=view_name, deleted=False).exists()

        self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/revenue_analytics_config/",
            data={"enabled": False},
        )

        assert not DataWarehouseJoin.objects.filter(team=self.team, source_table_name=view_name, deleted=False).exists()
        assert DataWarehouseJoin.objects.filter(team=self.team, source_table_name=view_name, deleted=True).exists()

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
                            "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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

    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_accepts_valid_prefix(self, _mock_validate):
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
                            "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
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


class TestCreateWebhook(APIBaseTest):
    def _webhook_result(self, success=True, error=None, extra_inputs=None):
        from posthog.temporal.data_imports.sources.common.base import WebhookCreationResult

        return WebhookCreationResult(success=success, error=error, extra_inputs=extra_inputs or {})

    def _create_stripe_source(self, job_inputs=None) -> ExternalDataSource:
        if job_inputs is None:
            job_inputs = {"stripe_secret_key": "sk_test_123"}
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs=job_inputs,
        )

    def _create_incremental_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team_id=self.team.pk,
            source=source,
            sync_type="incremental",
            should_sync=True,
        )

    def _create_webhook_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team_id=self.team.pk,
            source=source,
            sync_type="webhook",
            should_sync=True,
        )

    def _create_hog_function_template(self):
        from posthog.models.hog_function_template import HogFunctionTemplate

        return HogFunctionTemplate.objects.create(
            template_id="template-warehouse-source-stripe",
            name="Stripe warehouse source webhook",
            description="Receive Stripe webhook events for data warehouse ingestion",
            code="// test code",
            code_language="hog",
            inputs_schema=[
                {
                    "type": "string",
                    "key": "signing_secret",
                    "label": "Signing secret",
                    "required": False,
                    "secret": True,
                },
                {
                    "type": "boolean",
                    "key": "bypass_signature_check",
                    "label": "Bypass signature check",
                    "default": False,
                    "required": False,
                    "secret": False,
                },
                {
                    "type": "json",
                    "key": "schema_mapping",
                    "label": "Schema mapping",
                    "required": True,
                    "secret": False,
                    "hidden": True,
                },
                {
                    "type": "string",
                    "key": "source_id",
                    "label": "Source ID",
                    "required": True,
                    "secret": False,
                    "hidden": True,
                },
            ],
            type="warehouse_source_webhook",
            status="alpha",
            category=[],
        )

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_success(self, mock_create_webhook, _mock_flag):
        mock_create_webhook.return_value = self._webhook_result()
        from posthog.models.hog_functions.hog_function import HogFunction
        from posthog.temporal.data_imports.sources.stripe.constants import RESOURCE_TO_STRIPE_OBJECT_TYPE

        self._create_hog_function_template()
        source = self._create_stripe_source()
        schema = self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "/public/webhooks/dwh/" in data["webhook_url"]
        assert data["error"] is None

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        assert hog_function.template_id == "template-warehouse-source-stripe"
        assert hog_function.inputs is not None
        schema_mapping = hog_function.inputs["schema_mapping"]["value"]
        expected_object_type = RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_CUSTOMER_RESOURCE_NAME]
        assert expected_object_type in schema_mapping
        assert schema_mapping[expected_object_type] == str(schema.id)

        assert hog_function.inputs["source_id"]["value"] == str(source.pk)

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_create_webhook_no_job_inputs(self, _mock_flag):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs=None,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["message"] == "Source has no configuration"

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_external_creation_fails(self, mock_create_webhook, _mock_flag):
        mock_create_webhook.return_value = self._webhook_result(success=False, error="Permission denied")
        from posthog.models.hog_functions.hog_function import HogFunction

        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is False
        assert data["error"] == "Permission denied"
        assert "/public/webhooks/dwh/" in data["webhook_url"]

        assert HogFunction.objects.filter(team=self.team, type="warehouse_source_webhook").exists()

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_create_webhook_url_uses_cloud_deployment(self, mock_create_webhook, _mock_flag):
        mock_create_webhook.return_value = self._webhook_result()
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["webhook_url"].startswith("https://webhooks.us.posthog.com")

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    @override_settings(CLOUD_DEPLOYMENT=None, SITE_URL="https://my.posthog.instance")
    def test_create_webhook_url_uses_site_url_for_self_hosted(self, mock_create_webhook, _mock_flag):
        mock_create_webhook.return_value = self._webhook_result()
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["webhook_url"].startswith("https://my.posthog.instance")

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_merges_schemas_on_update(self, mock_create_webhook, _mock_flag):
        mock_create_webhook.return_value = self._webhook_result()
        from posthog.models.hog_functions.hog_function import HogFunction
        from posthog.temporal.data_imports.sources.stripe.constants import RESOURCE_TO_STRIPE_OBJECT_TYPE

        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CHARGE_RESOURCE_NAME)

        # First call: creates HogFunction with Charge schema
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )
        assert response.status_code == status.HTTP_200_OK

        # Now add a Customer schema and call again
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )
        assert response.status_code == status.HTTP_200_OK

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")

        assert hog_function.inputs is not None

        schema_mapping = hog_function.inputs["schema_mapping"]["value"]

        assert hog_function.inputs["source_id"]["value"] == str(source.pk)

        charge_object_type = RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_CHARGE_RESOURCE_NAME]
        customer_object_type = RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_CUSTOMER_RESOURCE_NAME]
        assert charge_object_type in schema_mapping
        assert customer_object_type in schema_mapping

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_create_webhook_template_not_in_db(self, _mock_flag):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "sync_hog_function_templates" in response.json()["message"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_saves_extra_inputs(self, mock_create_webhook, _mock_flag):
        from posthog.models.hog_functions.hog_function import HogFunction

        mock_create_webhook.return_value = self._webhook_result(extra_inputs={"signing_secret": "whsec_test123"})

        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["success"] is True

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        # signing_secret is marked as secret in the template, so it gets moved to encrypted_inputs on save
        assert hog_function.encrypted_inputs is not None
        assert hog_function.encrypted_inputs["signing_secret"]["value"] == "whsec_test123"

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs(self, mock_create_webhook, _mock_flag):
        from posthog.models.hog_functions.hog_function import HogFunction

        mock_create_webhook.return_value = self._webhook_result()

        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        # First create the webhook to set up the HogFunction
        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/")

        # Now update the inputs manually
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_manual123"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["success"] is True

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        assert hog_function.encrypted_inputs is not None
        assert hog_function.encrypted_inputs["signing_secret"]["value"] == "whsec_manual123"

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_update_webhook_inputs_rejects_invalid_keys(self, _mock_flag):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"nonexistent_key": "value"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid input keys" in response.json()["message"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_update_webhook_inputs_no_hog_function(self, _mock_flag):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_test"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No webhook function found" in response.json()["message"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_maps_all_webhook_schemas(self, mock_create_webhook, _mock_flag):
        """Regression: creating a source with multiple webhook tables then hitting the
        create_webhook endpoint must populate schema_mapping for every webhook schema.
        Webhook schemas have sync_type='webhook' (not 'incremental')."""
        mock_create_webhook.return_value = self._webhook_result()
        from posthog.models.hog_functions.hog_function import HogFunction
        from posthog.temporal.data_imports.sources.stripe.constants import RESOURCE_TO_STRIPE_OBJECT_TYPE

        self._create_hog_function_template()
        source = self._create_stripe_source()
        customer_schema = self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        charge_schema = self._create_webhook_schema(source, STRIPE_CHARGE_RESOURCE_NAME)
        invoice_schema = self._create_webhook_schema(source, STRIPE_INVOICE_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["success"] is True

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        assert hog_function.inputs is not None

        schema_mapping = hog_function.inputs["schema_mapping"]["value"]
        assert schema_mapping[RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_CUSTOMER_RESOURCE_NAME]] == str(customer_schema.id)
        assert schema_mapping[RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_CHARGE_RESOURCE_NAME]] == str(charge_schema.id)
        assert schema_mapping[RESOURCE_TO_STRIPE_OBJECT_TYPE[STRIPE_INVOICE_RESOURCE_NAME]] == str(invoice_schema.id)
        assert len(schema_mapping) == 3

        assert hog_function.inputs["source_id"]["value"] == str(source.pk)


class TestSensitiveFieldClassification(APIBaseTest):
    def test_classifies_password_fields_as_sensitive(self):
        fields: list[FieldType] = [
            SourceFieldInputConfig(
                name="host",
                label="Host",
                placeholder="",
                required=True,
                type=SourceFieldInputConfigType.TEXT,
                secret=False,
            ),
            SourceFieldInputConfig(
                name="password",
                label="Password",
                placeholder="",
                required=True,
                type=SourceFieldInputConfigType.PASSWORD,
                secret=True,
            ),
        ]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)
        assert "host" in nonsensitive
        assert "password" in sensitive
        assert "password" not in nonsensitive
        assert "host" not in sensitive

    def test_classifies_file_upload_as_sensitive(self):
        fields: list[FieldType] = [
            SourceFieldFileUploadConfig(
                name="key_file",
                label="Key file",
                required=True,
                fileFormat=SourceFieldFileUploadJsonFormatConfig(keys=["project_id", "private_key"]),
            ),
        ]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)
        assert "key_file" in sensitive
        assert "key_file" not in nonsensitive

    def test_classifies_select_with_nested_password(self):
        fields: list[FieldType] = [
            SourceFieldSelectConfig(
                name="auth_type",
                label="Auth",
                required=True,
                defaultValue="password",
                options=[
                    SourceFieldSelectConfigOption(
                        label="Password",
                        value="password",
                        fields=[
                            SourceFieldInputConfig(
                                name="user",
                                label="User",
                                placeholder="",
                                required=True,
                                type=SourceFieldInputConfigType.TEXT,
                                secret=False,
                            ),
                            SourceFieldInputConfig(
                                name="password",
                                label="Password",
                                placeholder="",
                                required=True,
                                type=SourceFieldInputConfigType.PASSWORD,
                                secret=True,
                            ),
                        ],
                    ),
                ],
            ),
        ]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)
        assert "auth_type" in nonsensitive
        assert "user" in nonsensitive
        assert "password" in sensitive

    def test_classifies_ssh_tunnel_nested_fields(self):
        fields: list[FieldType] = [SourceFieldSSHTunnelConfig(name="ssh_tunnel", label="SSH Tunnel")]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)
        assert "ssh_tunnel" in nonsensitive
        assert "host" in nonsensitive
        assert "port" in nonsensitive
        assert "username" in nonsensitive
        assert "auth" in nonsensitive
        assert "auth_type" in nonsensitive
        assert "password" in sensitive
        assert "passphrase" in sensitive
        assert "private_key" in sensitive

    def test_classifies_secret_flag_as_sensitive_regardless_of_type(self):
        fields: list[FieldType] = [
            SourceFieldInputConfig(
                name="client_private_key",
                label="Client private key",
                placeholder="",
                required=True,
                type=SourceFieldInputConfigType.TEXTAREA,
                secret=True,
            ),
            SourceFieldInputConfig(
                name="namespace",
                label="Namespace",
                placeholder="",
                required=True,
                type=SourceFieldInputConfigType.TEXT,
                secret=False,
            ),
        ]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)
        assert "client_private_key" in sensitive
        assert "client_private_key" not in nonsensitive
        assert "namespace" in nonsensitive
        assert "namespace" not in sensitive

    def test_strip_sensitive_from_dict_basic(self):
        data = {"host": "localhost", "password": "secret", "unknown_key": "val"}
        result = strip_sensitive_from_dict(data, nonsensitive={"host"}, sensitive={"password"})
        assert result == {"host": "localhost"}

    def test_strip_sensitive_from_dict_recursive(self):
        data = {
            "ssh_tunnel": {
                "enabled": True,
                "host": "bastion.example.com",
                "port": 22,
                "auth": {
                    "selection": "password",
                    "username": "ubuntu",
                    "password": "secret",
                    "private_key": "-----BEGIN-----",
                },
            },
        }
        nonsensitive = {"ssh_tunnel", "host", "port", "username", "auth"}
        sensitive = {"password", "private_key", "passphrase"}
        result = strip_sensitive_from_dict(data, nonsensitive, sensitive)

        assert result["ssh_tunnel"]["enabled"] is True
        assert result["ssh_tunnel"]["host"] == "bastion.example.com"
        assert result["ssh_tunnel"]["port"] == 22
        assert result["ssh_tunnel"]["auth"]["selection"] == "password"
        assert result["ssh_tunnel"]["auth"]["username"] == "ubuntu"
        assert "password" not in result["ssh_tunnel"]["auth"]
        assert "private_key" not in result["ssh_tunnel"]["auth"]

    def test_hyphenated_field_names_include_underscore_variant(self):
        """Fields with hyphens (e.g. "temporary-dataset") should also match the
        snake_case variant ("temporary_dataset") produced by dataclasses.asdict()."""
        fields: list[FieldType] = [
            SourceFieldSwitchGroupConfig(
                name="temporary-dataset",
                label="Temporary dataset",
                default=False,
                fields=cast(
                    list[FieldType],
                    [
                        SourceFieldInputConfig(
                            name="temporary_dataset_id",
                            label="Dataset ID",
                            placeholder="",
                            required=True,
                            type=SourceFieldInputConfigType.TEXT,
                            secret=False,
                        ),
                    ],
                ),
            ),
        ]
        nonsensitive, _ = get_nonsensitive_and_sensitive_field_names(fields)
        assert "temporary-dataset" in nonsensitive
        assert "temporary_dataset" in nonsensitive

    def test_strip_preserves_aliased_switch_group_from_to_dict(self):
        """job_inputs persisted via to_dict() uses snake_case keys even when
        the source field name uses hyphens. The strip function must keep these."""
        fields: list[FieldType] = [
            SourceFieldInputConfig(
                name="dataset_id",
                label="Dataset ID",
                placeholder="",
                required=True,
                type=SourceFieldInputConfigType.TEXT,
                secret=False,
            ),
            SourceFieldSwitchGroupConfig(
                name="temporary-dataset",
                label="Temporary dataset",
                default=False,
                fields=cast(
                    list[FieldType],
                    [
                        SourceFieldInputConfig(
                            name="temporary_dataset_id",
                            label="Dataset ID",
                            placeholder="",
                            required=True,
                            type=SourceFieldInputConfigType.TEXT,
                            secret=False,
                        ),
                    ],
                ),
            ),
        ]
        nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(fields)

        # Simulate job_inputs as persisted by dataclasses.asdict() (snake_case keys)
        persisted_data = {
            "dataset_id": "my-dataset",
            "temporary_dataset": {
                "enabled": True,
                "temporary_dataset_id": "tmp-dataset",
            },
        }
        result = strip_sensitive_from_dict(persisted_data, nonsensitive, sensitive)
        assert "temporary_dataset" in result
        assert result["temporary_dataset"]["enabled"] is True
        assert result["temporary_dataset"]["temporary_dataset_id"] == "tmp-dataset"

    def test_all_registered_sources_have_valid_classification(self):
        for source in SourceRegistry.get_all_sources().values():
            config = source.get_source_config
            nonsensitive, sensitive = get_nonsensitive_and_sensitive_field_names(config.fields)

            # No field should appear in both sets
            overlap = nonsensitive & sensitive
            assert not overlap, f"{config.name}: fields in both sets: {overlap}"

    def test_password_typed_fields_must_be_marked_secret(self):
        """A field rendered as type=PASSWORD that is not also `secret=True` is a misconfiguration:
        it would obscure on screen but still be returned in plain text from the API.
        """

        def collect_password_fields_without_secret(fields: list[FieldType]) -> list[str]:
            offenders: list[str] = []
            for field in fields:
                if isinstance(field, SourceFieldInputConfig):
                    if field.type == SourceFieldInputConfigType.PASSWORD and not field.secret:
                        offenders.append(field.name)
                elif isinstance(field, SourceFieldSwitchGroupConfig):
                    offenders.extend(collect_password_fields_without_secret(field.fields))
                elif isinstance(field, SourceFieldSelectConfig):
                    for option in field.options:
                        if option.fields:
                            offenders.extend(collect_password_fields_without_secret(option.fields))
            return offenders

        all_offenders: dict[str, list[str]] = {}
        for source in SourceRegistry.get_all_sources().values():
            config = source.get_source_config
            offenders = collect_password_fields_without_secret(config.fields)
            if offenders:
                all_offenders[config.name] = offenders

        assert not all_offenders, (
            f"PASSWORD-typed fields must also set secret=True to be redacted from API responses. "
            f"Offending fields: {all_offenders}"
        )

    def test_dynamic_classification_covers_old_hardcoded_allowlist(self):
        """Regression: all fields from the old hardcoded allowlist should be in the dynamic nonsensitive set."""

        old_allowed = {
            "stripe_account_id",
            "database",
            "host",
            "port",
            "user",
            "schema",
            "ssh_tunnel",
            "using_ssl",
            "region",
            "site_name",
            "subdomain",
            "email_address",
            "hubspot_integration_id",
            "custom_properties",
            "account_id",
            "warehouse",
            "role",
            "dataset_id",
            "temporary-dataset",
            "dataset_project",
            "customer_id",
            "google_ads_integration_id",
            "is_mcc_account",
            "spreadsheet_url",
            "linkedin_ads_integration_id",
            "meta_ads_integration_id",
            "sync_lookback_days",
            "reddit_integration_id",
            "salesforce_integration_id",
            "repository",
            "shopify_store_id",
            "namespace",
        }

        # Collect all nonsensitive field names across all sources
        all_nonsensitive: set[str] = set()
        for source in SourceRegistry.get_all_sources().values():
            config = source.get_source_config
            nonsensitive, _ = get_nonsensitive_and_sensitive_field_names(config.fields)
            all_nonsensitive.update(nonsensitive)

        missing = old_allowed - all_nonsensitive
        assert not missing, f"Old allowlist fields not covered by dynamic classification: {missing}"


class TestWebhookInfo(APIBaseTest):
    def _create_stripe_source(self, job_inputs=None) -> ExternalDataSource:
        if job_inputs is None:
            job_inputs = {"stripe_secret_key": "sk_test_123"}
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs=job_inputs,
        )

    def _create_postgres_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost"},
        )

    def _create_hog_function(self, source: ExternalDataSource, enabled: bool = True):
        from posthog.models.hog_functions.hog_function import HogFunction

        return HogFunction.objects.create(
            team=self.team,
            name="Stripe warehouse source webhook",
            type="warehouse_source_webhook",
            hog="// test",
            enabled=enabled,
            inputs_schema=[
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "secret": False},
                {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True, "secret": False},
            ],
            inputs={
                "source_id": {"value": str(source.pk)},
                "schema_mapping": {"value": {"customer": "schema-id-1", "charge": "schema-id-2"}},
            },
        )

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_webhook_info_non_webhook_source(self, _mock_flag):
        source = self._create_postgres_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["supports_webhooks"] is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_webhook_info_no_hog_function(self, _mock_flag):
        source = self._create_stripe_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["supports_webhooks"] is True
        assert data["exists"] is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info")
    def test_webhook_info_with_hog_function(self, mock_get_info, _mock_flag):
        from posthog.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(
            exists=True,
            url="https://webhooks.us.posthog.com/public/webhooks/dwh/test-id",
            status="enabled",
            enabled_events=["charge.created", "charge.updated"],
            description="PostHog data warehouse webhook",
        )

        source = self._create_stripe_source()
        hog_function = self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["supports_webhooks"] is True
        assert data["exists"] is True
        assert data["hog_function"]["id"] == str(hog_function.id)
        assert data["hog_function"]["enabled"] is True
        assert data["webhook_url"] is not None
        assert data["schema_mapping"] == {"customer": "schema-id-1", "charge": "schema-id-2"}
        assert data["external_status"]["exists"] is True
        assert data["external_status"]["status"] == "enabled"
        assert data["external_status"]["enabled_events"] == ["charge.created", "charge.updated"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info")
    def test_webhook_info_external_not_found(self, mock_get_info, _mock_flag):
        from posthog.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(exists=False)

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["exists"] is True
        assert data["external_status"]["exists"] is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info")
    def test_webhook_info_external_error(self, mock_get_info, _mock_flag):
        from posthog.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(
            exists=False,
            error="Your Stripe API key doesn't have permission to read webhooks.",
        )

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["exists"] is True
        assert data["external_status"]["error"] is not None

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_webhook_info_source_returns_none(self, _mock_flag):
        """When a source doesn't implement get_external_webhook_info, external_status should be null."""
        source = self._create_stripe_source()
        self._create_hog_function(source)

        with patch(
            "posthog.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info",
            return_value=None,
        ):
            response = self.client.get(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/"
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["exists"] is True
        assert data["external_status"] is None


class TestDeleteWebhook(APIBaseTest):
    def _create_stripe_source(self, job_inputs=None) -> ExternalDataSource:
        if job_inputs is None:
            job_inputs = {"stripe_secret_key": "sk_test_123"}
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs=job_inputs,
        )

    def _create_hog_function(self, source: ExternalDataSource, enabled: bool = True):
        from posthog.models.hog_functions.hog_function import HogFunction

        return HogFunction.objects.create(
            team=self.team,
            name="Stripe warehouse source webhook",
            type="warehouse_source_webhook",
            hog="// test",
            enabled=enabled,
            inputs_schema=[
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "secret": False},
                {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True, "secret": False},
            ],
            inputs={
                "source_id": {"value": str(source.pk)},
                "schema_mapping": {"value": {"customer": "schema-id-1"}},
            },
        )

    def _create_incremental_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team_id=self.team.pk,
            source=source,
            sync_type="incremental",
            should_sync=True,
        )

    def _create_webhook_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team_id=self.team.pk,
            source=source,
            sync_type="webhook",
            should_sync=True,
        )

    def _create_full_refresh_schema(self, source: ExternalDataSource, name: str) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            name=name,
            team_id=self.team.pk,
            source=source,
            sync_type="full_refresh",
            should_sync=True,
        )

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_delete_webhook_success(self, mock_delete_webhook, _mock_flag):
        from posthog.temporal.data_imports.sources.common.base import WebhookDeletionResult

        mock_delete_webhook.return_value = WebhookDeletionResult(success=True)

        source = self._create_stripe_source()
        self._create_full_refresh_schema(source, "Customers")
        hog_function = self._create_hog_function(source)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["external_deleted"] is True
        assert data["error"] is None

        hog_function.refresh_from_db()
        assert hog_function.deleted is True
        assert hog_function.enabled is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_delete_webhook_blocked_by_webhook_schemas(self, _mock_flag):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, "Customers")
        self._create_hog_function(source)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "webhook sync" in response.json()["message"]
        assert "Customers" in response.json()["message"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_delete_webhook_external_fails_still_deletes_hog_function(self, mock_delete_webhook, _mock_flag):
        from posthog.temporal.data_imports.sources.common.base import WebhookDeletionResult

        mock_delete_webhook.return_value = WebhookDeletionResult(success=False, error="Permission denied")

        source = self._create_stripe_source()
        self._create_full_refresh_schema(source, "Customers")
        hog_function = self._create_hog_function(source)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["external_deleted"] is False
        assert data["error"] == "Permission denied"

        hog_function.refresh_from_db()
        assert hog_function.deleted is True
        assert hog_function.enabled is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_delete_webhook_no_hog_function(self, _mock_flag):
        source = self._create_stripe_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["external_deleted"] is False

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_delete_webhook_non_webhook_source(self, _mock_flag):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={"host": "localhost"},
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not support webhooks" in response.json()["message"]

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    def test_delete_webhook_no_job_inputs_still_cleans_up_hog_function(self, _mock_flag):
        source = self._create_stripe_source(job_inputs={})
        hog_function = self._create_hog_function(source)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["external_deleted"] is False

        hog_function.refresh_from_db()
        assert hog_function.deleted is True
        assert hog_function.enabled is False


class TestDestroySourceCleansUpWebhook(APIBaseTest):
    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("posthog.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_destroy_source_deletes_webhook_and_hog_function(self, mock_delete_webhook, _mock_flag):
        from posthog.models.hog_functions.hog_function import HogFunction
        from posthog.temporal.data_imports.sources.common.base import WebhookDeletionResult

        mock_delete_webhook.return_value = WebhookDeletionResult(success=True)

        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        hog_function = HogFunction.objects.create(
            team=self.team,
            name="Stripe warehouse source webhook",
            type="warehouse_source_webhook",
            hog="// test",
            enabled=True,
            inputs_schema=[
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "secret": False},
            ],
            inputs={"source_id": {"value": str(source.pk)}},
        )

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204
        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()

        hog_function.refresh_from_db()
        assert hog_function.deleted is True
        assert hog_function.enabled is False
        mock_delete_webhook.assert_called_once()

    @patch("posthog.temporal.data_imports.sources.stripe.source.is_webhook_feature_flag_enabled", return_value=True)
    @patch("products.data_warehouse.backend.api.external_data_source.capture_exception")
    @patch(
        "posthog.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook",
        side_effect=Exception("Stripe API error"),
    )
    def test_destroy_source_continues_if_webhook_cleanup_fails(
        self, _mock_delete_webhook, mock_capture_exception, _mock_flag
    ):
        from posthog.models.hog_functions.hog_function import HogFunction

        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        HogFunction.objects.create(
            team=self.team,
            name="Stripe warehouse source webhook",
            type="warehouse_source_webhook",
            hog="// test",
            enabled=True,
            inputs_schema=[
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "secret": False},
            ],
            inputs={"source_id": {"value": str(source.pk)}},
        )

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204
        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()
        assert mock_capture_exception.called


class TestDestroySourceCleansUpCompanionTables(APIBaseTest):
    def test_destroy_source_deletes_companion_cdc_tables(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )

        main_table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="test_orders",
            external_data_source_id=source.pk,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="s3://bucket/main",
        )
        schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            table=main_table,
        )

        # Companion _cdc table — linked to source but NOT to schema.table
        companion_table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="test_orders_cdc",
            external_data_source_id=source.pk,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="s3://bucket/cdc",
        )

        # Unrelated table from another source — should NOT be deleted
        other_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_456"},
        )
        unrelated_table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="other_table",
            external_data_source_id=other_source.pk,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="s3://bucket/other",
        )

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204

        # Main table soft-deleted via schema.table
        main_table.refresh_from_db()
        assert main_table.deleted is True

        # Schema soft-deleted
        schema.refresh_from_db()
        assert schema.deleted is True

        # Companion _cdc table soft-deleted by the companion cleanup query
        companion_table.refresh_from_db()
        assert companion_table.deleted is True

        # Unrelated table NOT deleted
        unrelated_table.refresh_from_db()
        assert unrelated_table.deleted is False


class TestExternalDataSourceCreateSerializerValidation(APIBaseTest):
    @parameterized.expand(
        [
            ("missing_source_type", {"payload": {"host": "localhost"}}),
            ("missing_payload", {"source_type": "Postgres"}),
            ("invalid_source_type", {"source_type": "InvalidType", "payload": {"host": "localhost"}}),
        ]
    )
    def test_create_rejects_invalid_input(self, _name: str, data: dict) -> None:
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data,
            format="json",
        )
        assert response.status_code == 400
