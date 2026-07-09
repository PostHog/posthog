import json
import uuid
import typing as t
from datetime import timedelta
from typing import cast

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, FuzzyInt
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

import psycopg
from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError
from sshtunnel import BaseSSHTunnelForwarderError

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

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.data_warehouse.backend.direct_postgres import DIRECT_POSTGRES_URL_PATTERN
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.presentation.views.external_data_schema import ExternalDataSchemaSerializer
from products.data_warehouse.backend.presentation.views.external_data_source import (
    get_direct_connection_metadata,
    get_nonsensitive_and_sensitive_field_names,
    strip_sensitive_from_dict,
)
from products.revenue_analytics.backend.joins import get_customer_revenue_view_name
from products.warehouse_sources.backend.facade.models import (
    CustomOAuth2Integration,
    DataWarehouseTable,
    ExternalDataJob,
    ExternalDataSchema,
    ExternalDataSource,
    PendingSourceCredential,
    sync_frequency_interval_to_sync_frequency,
)
from products.warehouse_sources.backend.facade.types import IncrementalFieldType
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery import BigQuerySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    WebhookCreationResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.custom.source import (
    MAX_CUSTOM_SOURCES_PER_TEAM,
    PREVIEW_DEFAULT_ROWS,
    PREVIEW_MAX_ROWS,
    ManifestValidationError,
    PreviewResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    PostgresDiscoveredSchema,
    SSLRequiredError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
    BALANCE_TRANSACTION_RESOURCE_NAME as STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    COUPON_RESOURCE_NAME as STRIPE_COUPON_RESOURCE_NAME,
    CREDIT_NOTE_RESOURCE_NAME as STRIPE_CREDIT_NOTE_RESOURCE_NAME,
    CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME as STRIPE_CUSTOMER_BALANCE_TRANSACTION_RESOURCE_NAME,
    CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME as STRIPE_CUSTOMER_PAYMENT_METHOD_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    DISCOUNT_RESOURCE_NAME as STRIPE_DISCOUNT_RESOURCE_NAME,
    DISPUTE_RESOURCE_NAME as STRIPE_DISPUTE_RESOURCE_NAME,
    INVOICE_ITEM_RESOURCE_NAME as STRIPE_INVOICE_ITEM_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PAYOUT_RESOURCE_NAME as STRIPE_PAYOUT_RESOURCE_NAME,
    PRICE_RESOURCE_NAME as STRIPE_PRICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    REFUND_RESOURCE_NAME as STRIPE_REFUND_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.settings import (
    ENDPOINTS as STRIPE_ENDPOINTS,
)


class TestExternalDataSource(APIBaseTest):
    def _create_external_data_source(self, created_via: str = ExternalDataSource.CreatedVia.WEB) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            created_via=created_via,
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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
                        {"name": STRIPE_COUPON_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                        {"name": STRIPE_DISCOUNT_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_rejects_row_filters_for_source_without_pushdown(self, _mock_validate):
        # Stripe doesn't push filters into a SQL WHERE — accepting one on creation would save it
        # and then silently sync unfiltered rows (mirrors the PATCH-path
        # test_row_filters_rejected_for_source_without_pushdown in test_external_data_schema.py).
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {
                            "name": STRIPE_CUSTOMER_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "full_refresh",
                            "row_filters": [{"column": "id", "operator": ">", "value": "10"}],
                        },
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not supported for this source type" in str(response.json())
        assert not ExternalDataSource.objects.filter(team_id=self.team.pk).exists()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.sync_discover_schemas_schedule")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_creates_discovery_schedule(self, _mock_validate, mock_sync_discover):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_SUBSCRIPTION_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 201, response.json()
        mock_sync_discover.assert_called_once()
        assert mock_sync_discover.call_args.kwargs == {"create": True}
        # First positional arg is the freshly created ExternalDataSource model
        created_source = mock_sync_discover.call_args.args[0]
        assert str(created_source.id) == response.json()["id"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.sync_discover_schemas_schedule")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_direct_query_source_skips_discovery_schedule(self, mock_get_source, mock_sync_discover):
        # Direct-query sources resolve schemas at query time and opt out of all
        # background sync — no discovery schedule should be created.
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
                columns=[("id", "integer", False)],
                foreign_keys=[],
            ),
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
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

        assert response.status_code == 201, response.json()
        mock_sync_discover.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_delete_on_missing_schemas(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": False,
                },
            },
        )

        assert response.status_code == 400
        assert ExternalDataSource.objects.count() == 0

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_delete_on_bad_schema(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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

    @parameterized.expand(
        [
            (ExternalDataSource.CreatedVia.WEB,),
            (ExternalDataSource.CreatedVia.API,),
            (ExternalDataSource.CreatedVia.MCP,),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_persists_created_via(self, created_via, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": created_via,
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 201, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        assert source.created_via == created_via

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_defaults_created_via_to_api_when_missing(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 201, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        assert source.created_via == ExternalDataSource.CreatedVia.API

    def test_create_external_data_source_rejects_invalid_created_via(self):
        # created_via choice validation happens before credentials, so no StripeSource mock is needed here.
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "hacker",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 400
        assert response.json()["attr"] == "created_via"
        assert ExternalDataSource.objects.count() == 0

    def test_patch_external_data_source_ignores_created_via(self):
        source = self._create_external_data_source(created_via=ExternalDataSource.CreatedVia.WEB)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"created_via": "mcp"},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.created_via == ExternalDataSource.CreatedVia.WEB

    def test_patch_external_data_source_accepts_null_created_via(self):
        # Historical rows created before migration 0049 have created_via=NULL. The
        # settings page spreads the GET payload back into PATCH, so null round-trips
        # through the serializer. allow_null=True keeps that path working.
        source = self._create_external_data_source()
        ExternalDataSource.objects.filter(pk=source.pk).update(created_via=None)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"created_via": None, "description": "edited"},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.created_via is None
        assert source.description == "edited"

    @parameterized.expand(
        [
            ("omitted_defaults_true", {}, True),
            ("explicit_true", {"direct_query_enabled": True}, True),
            ("explicit_false", {"direct_query_enabled": False}, False),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_direct_query_enabled(self, _name, body, expected, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                **body,
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )

        assert response.status_code == 201, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        assert source.direct_query_enabled is expected

    @patch("posthog.event_usage.posthoganalytics.capture")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_reports_analytics_event(self, _mock_validate, mock_capture):
        # report_user_action runs for real (not mocked) and the request carries the MCP marker, so the
        # test fails if the request stops being forwarded or `source` stops landing — the mcp/ui/api
        # attribution this PR exists to deliver.
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "mcp",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        assert response.status_code == 201, response.json()
        events = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "data warehouse source created"]
        assert len(events) == 1
        properties = events[0].kwargs["properties"]
        assert properties["source"] == "mcp"  # request-derived transport
        assert properties["created_via"] == "mcp"  # caller's explicit intent
        assert properties["source_type"] == "Stripe"
        assert properties["source_id"] == str(response.json()["id"])

    @patch("posthog.event_usage.posthoganalytics.capture")
    def test_patch_external_data_source_reports_analytics_event(self, mock_capture):
        # Source originally created via the UI, then edited over MCP: the event must carry both the
        # edit's transport (source=mcp) and the unchanged original origin (created_via=web).
        source = self._create_external_data_source(created_via=ExternalDataSource.CreatedVia.WEB)

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"description": "edited"},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        assert response.status_code == 200, response.json()
        events = [c for c in mock_capture.call_args_list if c.kwargs.get("event") == "data warehouse source updated"]
        assert len(events) == 1
        properties = events[0].kwargs["properties"]
        assert properties["source"] == "mcp"  # who performed the edit
        assert properties["created_via"] == ExternalDataSource.CreatedVia.WEB  # original origin, preserved
        assert properties["source_type"] == "Stripe"
        assert properties["source_id"] == str(source.pk)

    def test_patch_external_data_source_toggles_direct_query_enabled(self):
        source = self._create_external_data_source()
        assert source.direct_query_enabled is True

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"direct_query_enabled": False},
        )

        assert response.status_code == 200, response.json()
        assert response.json()["direct_query_enabled"] is False
        source.refresh_from_db()
        assert source.direct_query_enabled is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials_for_access_method",
        return_value=(True, None),
    )
    def test_patch_external_data_source_preserves_cdc_config_when_schema_cleared(self, _mock_validate):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "user": "test",
                "password": "test",
                "schema": "public",
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "posthog_slot",
                "cdc_publication_name": "posthog_pub",
                "cdc_auto_drop_slot": False,
                "cdc_lag_warning_threshold_mb": 512,
                "cdc_lag_critical_threshold_mb": 1024,
                "cdc_consistent_point": "0/AA",
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "testdb",
                    "user": "test",
                    "schema": "",
                    "cdc_enabled": False,
                    "cdc_management_mode": "self_managed",
                    "cdc_slot_name": "attacker_slot",
                    "cdc_publication_name": "attacker_pub",
                    "cdc_auto_drop_slot": True,
                    "cdc_lag_warning_threshold_mb": 1,
                    "cdc_lag_critical_threshold_mb": 2,
                    "cdc_consistent_point": "0/BAD",
                }
            },
            format="json",
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["schema"] == ""
        assert str(source.job_inputs["cdc_enabled"]) == "True"
        assert source.job_inputs["cdc_management_mode"] == "posthog"
        assert source.job_inputs["cdc_slot_name"] == "posthog_slot"
        assert source.job_inputs["cdc_publication_name"] == "posthog_pub"
        assert str(source.job_inputs["cdc_auto_drop_slot"]) == "False"
        assert str(source.job_inputs["cdc_lag_warning_threshold_mb"]) == "512"
        assert str(source.job_inputs["cdc_lag_critical_threshold_mb"]) == "1024"
        assert source.job_inputs["cdc_consistent_point"] == "0/AA"

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
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
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
        return_value=True,
    )
    def test_bulk_update_schemas_runs_deferred_temporal_updates(self, _mock_workflow_exists):
        # Enabled schema with an existing schedule: a frequency change re-issues (updates) it.
        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with patch(
            "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
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
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas_runs_source_discovery_outside_transaction(self, _mock_workflow_exists):
        # `_is_webhook_only_schema` reaches the external source (e.g. Google Ads token refresh + field
        # query). It must run before the per-schema transaction opens — running it inside update()'s
        # transaction held the DB connection idle-in-transaction long enough for the server to close it.

        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="Customers",
            team_id=self.team.pk,
            source=source,
            should_sync=False,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        # The bulk loop opens a per-schema transaction (a nested savepoint) around update(). Compare the
        # savepoint depth at call time against the baseline before the request: equal ⇒ called from the
        # pre-transaction warm step (the fix); baseline + 1 ⇒ called inside update()'s transaction.
        baseline_savepoint_depth = len(connection.savepoint_ids)
        savepoint_depth_at_call: list[int] = []

        def record_savepoint_depth(_schema):
            savepoint_depth_at_call.append(len(connection.savepoint_ids))
            return False

        with patch.object(ExternalDataSchemaSerializer, "_is_webhook_only_schema", side_effect=record_savepoint_depth):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
                data={"schemas": [{"id": str(schema.id), "should_sync": True, "sync_type": "full_refresh"}]},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        # Called exactly once (memoized across warm + update), outside the per-schema transaction.
        assert savepoint_depth_at_call == [baseline_savepoint_depth]
        schema.refresh_from_db()
        assert schema.should_sync is True

    @parameterized.expand(
        [
            (
                "db_error",
                psycopg.OperationalError("the connection is closed"),
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "database",
            ),
            (
                "validation_error",
                ValidationError("Table1 cannot be changed"),
                status.HTTP_400_BAD_REQUEST,
                "cannot be changed",
            ),
        ]
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas_one_schema_failing_does_not_block_others(
        self, _name, raised_exception, expected_status, expected_detail_substring, _mock_workflow_exists
    ):
        # Each schema commits in its own transaction. A failure on one schema — a database error
        # mid-save, or a validation error raised inside update() — must not roll back or block the
        # others: every schema is attempted, and the failures are reported per schema (503 for a
        # database error, 400 when it is only validation) instead of 500ing the whole batch.
        from products.data_warehouse.backend.presentation.views.external_data_schema import ExternalDataSchemaSerializer

        source = self._create_external_data_source()
        schemas = [
            ExternalDataSchema.objects.create(
                name=f"Table{i}",
                team_id=self.team.pk,
                source=source,
                should_sync=True,
                sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
            )
            for i in range(3)
        ]
        original_interval = schemas[1].sync_frequency_interval

        original_update = ExternalDataSchemaSerializer.update
        attempted = 0

        def _failing_update(serializer_self, instance, validated_data):
            nonlocal attempted
            attempted += 1
            if attempted == 2:
                raise raised_exception
            return original_update(serializer_self, instance, validated_data)

        with (
            patch.object(ExternalDataSchemaSerializer, "update", _failing_update),
            patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow"
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
                data={"schemas": [{"id": str(s.id), "sync_frequency": "7day"} for s in schemas]},
                format="json",
            )

        # Every schema is attempted despite the second one failing.
        assert attempted == 3
        # The failure is surfaced with the right status and names only the schema that failed.
        assert response.status_code == expected_status
        detail = response.json()["detail"]
        assert "Table1" in detail
        assert expected_detail_substring in detail
        assert "Table0" not in detail
        assert "Table2" not in detail

        for schema in schemas:
            schema.refresh_from_db()
        # The schemas before and after the failure are committed...
        assert sync_frequency_interval_to_sync_frequency(schemas[0].sync_frequency_interval) == "7day"
        assert sync_frequency_interval_to_sync_frequency(schemas[2].sync_frequency_interval) == "7day"
        # ...and the one that failed keeps its original frequency.
        assert schemas[1].sync_frequency_interval == original_interval

    def test_bulk_update_schemas_invalid_payload_rejected_before_any_write(self):
        # The batch is validated up front (per-schema is_valid), so an invalid payload rejects the
        # whole request with nothing written — even the valid schema listed alongside it is not
        # committed. With per-schema commits, this preflight is what keeps a bad batch all-or-nothing.
        source = self._create_external_data_source()
        valid_schema = ExternalDataSchema.objects.create(
            name="Valid",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        invalid_schema = ExternalDataSchema.objects.create(
            name="Invalid",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )
        valid_original = valid_schema.sync_frequency_interval
        invalid_original = invalid_schema.sync_frequency_interval

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
            data={
                "schemas": [
                    {"id": str(valid_schema.id), "sync_frequency": "7day"},
                    {"id": str(invalid_schema.id), "sync_frequency": "not_a_real_frequency"},
                ]
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

        valid_schema.refresh_from_db()
        invalid_schema.refresh_from_db()
        # Nothing was persisted — the valid schema, listed first, was not committed.
        assert valid_schema.sync_frequency_interval == valid_original
        assert invalid_schema.sync_frequency_interval == invalid_original

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas_fails_when_schedule_update_fails_after_save(self, _mock_workflow_exists):
        # When a schema's row commits but its Temporal schedule update fails in the post-commit step,
        # the request fails — the batch did not fully apply. The committed row stands (it can't be
        # un-committed), and the failure is logged with the schema id.
        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="Table0",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.sync_external_data_job_workflow",
                side_effect=Exception("temporal unavailable"),
            ),
            patch("products.data_warehouse.backend.presentation.views.external_data_source.logger") as mock_logger,
        ):
            try:
                response = self.client.patch(
                    f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
                    data={"schemas": [{"id": str(schema.id), "sync_frequency": "7day"}]},
                    format="json",
                )
            except Exception:
                response = None

        # The request did not succeed — it either raised or returned a server error.
        assert response is None or response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
        # The per-schema commit happened before the schedule update, so the row is still persisted...
        schema.refresh_from_db()
        assert sync_frequency_interval_to_sync_frequency(schema.sync_frequency_interval) == "7day"
        # ...and the failure was logged with the schema id.
        assert any(call.kwargs.get("schema_id") == str(schema.id) for call in mock_logger.warning.call_args_list)

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_schema.external_data_workflow_exists",
        return_value=False,
    )
    def test_bulk_update_schemas_webhook_reconcile_raising_does_not_500(self, _mock_workflow_exists):
        # Webhook reconcile runs as a deferred post-commit hook in the bulk path, AFTER the
        # atomic block. If it raised there it would 500 the request with the rows already
        # committed. Guard that a raising reconcile is swallowed and the response stays 200.
        from products.data_warehouse.backend.logic.external_data_source.webhooks import WebhookHogFunctionCreateResult
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
            SourceSchema as _SourceSchema,
        )

        source = self._create_external_data_source()
        schema = ExternalDataSchema.objects.create(
            name="Charge",
            team_id=self.team.pk,
            source=source,
            should_sync=True,
            sync_type=ExternalDataSchema.SyncType.FULL_REFRESH,
        )

        mock_hog_function = MagicMock()
        mock_hog_function.id = uuid.uuid4()
        mock_hog_function.inputs = {"schema_mapping": {"value": {}}, "source_id": {"value": "test-source-id"}}
        mock_hog_fn_result = WebhookHogFunctionCreateResult(
            hog_function=mock_hog_function,
            webhook_url="https://test.com/webhook",
            hog_function_created=False,
        )
        mock_webhook_schemas = [
            _SourceSchema(name="Charge", supports_incremental=True, supports_append=True, supports_webhooks=True),
        ]

        with (
            patch(
                "products.data_warehouse.backend.presentation.views.external_data_schema.get_or_create_webhook_hog_function",
                return_value=mock_hog_fn_result,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.sync_webhook_events",
                side_effect=ValueError("Missing Stripe API key"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_schemas",
                return_value=mock_webhook_schemas,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook",
                return_value=WebhookCreationResult(success=True),
            ),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.id}/bulk_update_schemas",
                data={
                    "schemas": [
                        {
                            "id": str(schema.id),
                            "sync_type": "webhook",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                        }
                    ]
                },
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        schema.refresh_from_db()
        assert schema.sync_type == ExternalDataSchema.SyncType.WEBHOOK

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_prefix_external_data_source(self, _mock_validate):
        # Create no prefix

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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
                "created_via": "web",
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
                "created_via": "web",
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
                "created_via": "web",
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

    def _make_external_data_source(
        self, source_type: str = "Postgres", prefix: t.Optional[str] = None, deleted: bool = False
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type=source_type,
            created_by=self.user,
            prefix=prefix,
            deleted=deleted,
            job_inputs={},
        )

    @parameterized.expand(
        [
            # (description, existing_sources, requested_prefix, expected_status, expected_message)
            ("empty team allows no prefix", [], "", 200, None),
            ("empty team allows any prefix", [], "foo_", 200, None),
            (
                "only prefixed sources allow new no-prefix source",
                [("foo_", False), ("bar_", False)],
                "",
                200,
                None,
            ),
            (
                "only prefixed sources allow new distinct prefix",
                [("foo_", False)],
                "baz_",
                200,
                None,
            ),
            (
                "duplicate prefix is rejected",
                [("foo_", False)],
                "foo_",
                400,
                "Prefix already exists",
            ),
            (
                "no-prefix source (null) blocks another no-prefix",
                [(None, False)],
                "",
                400,
                "Source type already exists. Prefix is required",
            ),
            (
                "no-prefix source (empty string) blocks another no-prefix",
                [("", False)],
                "",
                400,
                "Source type already exists. Prefix is required",
            ),
            (
                "no-prefix source still allows a prefixed source",
                [(None, False)],
                "foo_",
                200,
                None,
            ),
            (
                # Regression: GitHub issue #60559
                "soft-deleted no-prefix source does not block recreation",
                [(None, True), ("foo_", False), ("bar_", False)],
                "",
                200,
                None,
            ),
            (
                "soft-deleted prefix does not block reuse",
                [("foo_", True)],
                "foo_",
                200,
                None,
            ),
        ]
    )
    def test_source_prefix_validation(
        self,
        _description: str,
        existing_sources: list[tuple[t.Optional[str], bool]],
        requested_prefix: str,
        expected_status: int,
        expected_message: t.Optional[str],
    ) -> None:
        for prefix, deleted in existing_sources:
            self._make_external_data_source(source_type="Postgres", prefix=prefix, deleted=deleted)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/source_prefix/",
            data={"source_type": "Postgres", "prefix": requested_prefix},
        )

        self.assertEqual(response.status_code, expected_status)
        if expected_message is not None:
            self.assertEqual(response.json(), {"message": expected_message})

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_can_recreate_no_prefix_source_after_deletion(self, _mock_validate):
        # Regression for GitHub #60559: deleting the only no-prefix source of a
        # type must allow recreating one with the same (empty) prefix, even when
        # other prefixed sources of the same type still exist.
        self._make_external_data_source(source_type="Stripe", prefix="foo_")

        create_response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        self.assertEqual(create_response.status_code, 201, create_response.json())
        source_id = create_response.json()["id"]

        delete_response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source_id}")
        self.assertEqual(delete_response.status_code, 204)

        recreate_response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {"name": STRIPE_CUSTOMER_RESOURCE_NAME, "should_sync": True, "sync_type": "full_refresh"},
                    ],
                },
            },
        )
        self.assertEqual(recreate_response.status_code, 201, recreate_response.json())

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_missing_field(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_missing_type(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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

    @parameterized.expand(
        [
            ("too_large", 5_184_001),
            ("negative", -1),
            ("non_integer_string", "soon"),
            ("non_integer_float", 1.5),
            ("boolean", True),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_invalid_lookback(
        self, _name: str, lookback_value: object, _mock_validate: MagicMock
    ):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                            "incremental_field_lookback_seconds": lookback_value,
                        },
                    ],
                },
            },
        )
        assert response.status_code == 400
        assert len(ExternalDataSource.objects.all()) == 0

    @parameterized.expand(
        [
            ("max_allowed", 5_184_000),
            ("zero", 0),
            ("whole_number_float", 3600.0),
            ("none", None),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_create_external_data_source_incremental_valid_lookback(
        self, _name: str, lookback_value: object, _mock_validate: MagicMock
    ):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "payload": {
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"},
                    "schemas": [
                        {
                            "name": STRIPE_BALANCE_TRANSACTION_RESOURCE_NAME,
                            "should_sync": True,
                            "sync_type": "incremental",
                            "incremental_field": "created",
                            "incremental_field_type": "integer",
                            "incremental_field_lookback_seconds": lookback_value,
                        },
                    ],
                },
            },
        )
        assert response.status_code == 201

    def test_create_external_data_source_bigquery_removes_project_id_prefix(self):
        """Test we remove the `project_id` prefix of a `dataset_id`."""
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.get_schemas",
                return_value=[
                    SourceSchema(
                        name="my_table",
                        supports_incremental=False,
                        supports_append=False,
                        columns=[("something", "DATE", False)],
                    )
                ],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
                return_value=(True, None),
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "source_type": "BigQuery",
                    "created_via": "web",
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
                "created_via": "web",
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
        # The list no longer builds the full HogQL Database (only needed to serialize table columns,
        # which the list omits), so it's much cheaper than the single-source read path.
        with self.assertNumQueries(FuzzyInt(13, 15)):
            response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 2)

    def test_list_omits_table_columns_but_retrieve_includes_them(self):
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
        ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="Accounts",
            should_sync=True,
            table=table,
        )

        # The list view never reads schemas[].table.columns, so it skips the expensive
        # HogQL field serialization and returns an empty column list.
        list_payload = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/").json()
        list_table = list_payload["results"][0]["schemas"][0]["table"]
        self.assertEqual(list_table["name"], "Accounts")
        self.assertEqual(list_table["columns"], [])

        # The single-source read still populates columns for the schema detail page.
        retrieve_payload = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}").json()
        retrieve_columns = retrieve_payload["schemas"][0]["table"]["columns"]
        self.assertTrue(any(column["key"] == "id" for column in retrieve_columns))

    def _create_searchable_source(self, source_type: str, prefix: str) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type=source_type,
            created_by=self.user,
            prefix=prefix,
        )

    # Sentinel resolved to a freshly-created source's opaque internal source_id at runtime,
    # to assert that searching by it no longer matches.
    SEARCH_BY_INTERNAL_SOURCE_ID = object()

    @parameterized.expand(
        [
            ("by_source_type", "Stripe", ["prod_payments"]),
            ("by_source_type_other", "Postgres", ["analytics"]),
            ("by_prefix_partial", "prod_", ["prod_payments"]),
            ("by_prefix_full", "analytics", ["analytics"]),
            ("no_match", "nonexistent", []),
            ("internal_source_id_is_not_searchable", SEARCH_BY_INTERNAL_SOURCE_ID, []),
        ]
    )
    def test_list_external_data_source_search(self, _name, term, expected_prefixes):
        sources = {
            "prod_payments": self._create_searchable_source(source_type="Stripe", prefix="prod_payments"),
            "analytics": self._create_searchable_source(source_type="Postgres", prefix="analytics"),
        }
        if term is self.SEARCH_BY_INTERNAL_SOURCE_ID:
            term = sources["analytics"].source_id

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/?search={term}")

        assert response.status_code == 200
        returned_prefixes = sorted(r["prefix"] for r in response.json()["results"])
        assert returned_prefixes == sorted(expected_prefixes)

    def test_connections_returns_lightweight_direct_connection_options(self):
        postgres_source = ExternalDataSource.objects.create(
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
        mysql_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="MySQL",
            created_by=self.user,
            prefix="Reporting MySQL",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "password": "secret"},
            connection_metadata={"engine": "mysql", "database": "warehouse", "version": "9.6.0"},
        )
        snowflake_source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Snowflake",
            created_by=self.user,
            prefix="Analytics Snowflake",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"account_id": "acct", "database": "TPCH_SF1"},
            connection_metadata={"engine": "snowflake", "database": "TPCH_SF1"},
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connections/")

        self.assertEqual(response.status_code, 200)
        payload = sorted(response.json(), key=lambda item: item["prefix"])
        self.assertEqual(
            payload,
            [
                {
                    "id": str(snowflake_source.pk),
                    "prefix": "Analytics Snowflake",
                    "engine": "snowflake",
                },
                {
                    "id": str(postgres_source.pk),
                    "prefix": "Primary database",
                    "engine": "duckdb",
                },
                {
                    "id": str(mysql_source.pk),
                    "prefix": "Reporting MySQL",
                    "engine": "mysql",
                },
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source.SnowflakeSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GithubSource.validate_credentials",
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
                "created_via",
                "status",
                "source_type",
                "latest_error",
                "prefix",
                "description",
                "access_method",
                "direct_query_enabled",
                "engine",
                "last_run_at",
                "schemas",
                "job_inputs",
                "revenue_analytics_config",
                "user_access_level",
                "supports_webhooks",
                "supports_column_selection",
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
                    "incremental_field_lookback_seconds": None,
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
                    "enabled_columns": None,
                    "masked_columns": None,
                    "row_filters": None,
                    "available_columns": [],
                    "source": None,
                }
            ],
        )

    @parameterized.expand(
        [
            (
                "failed_disabled_schema_ignored",
                ExternalDataSchema.Status.FAILED,
                ExternalDataSchema.Status.COMPLETED,
                ExternalDataSchema.Status.COMPLETED,
            ),
            (
                "billing_limit_reached_disabled_schema_ignored",
                ExternalDataSchema.Status.BILLING_LIMIT_REACHED,
                ExternalDataSchema.Status.COMPLETED,
                ExternalDataSchema.Status.COMPLETED,
            ),
            (
                "billing_limit_too_low_disabled_schema_ignored",
                ExternalDataSchema.Status.BILLING_LIMIT_TOO_LOW,
                ExternalDataSchema.Status.RUNNING,
                ExternalDataSchema.Status.RUNNING,
            ),
            (
                "failed_enabled_schema_still_propagates",
                ExternalDataSchema.Status.COMPLETED,
                ExternalDataSchema.Status.FAILED,
                ExternalDataSchema.Status.FAILED,
            ),
        ]
    )
    def test_status_excludes_disabled_schemas_from_negative_statuses(
        self,
        _name: str,
        disabled_schema_status: str,
        enabled_schema_status: str,
        expected_source_status: str,
    ):
        source = self._create_external_data_source()
        ExternalDataSchema.objects.create(
            name="DisabledWithError",
            team_id=self.team.pk,
            source_id=source.pk,
            table=None,
            should_sync=False,
            status=disabled_schema_status,
            latest_error="boom",
        )
        ExternalDataSchema.objects.create(
            name="EnabledHealthy",
            team_id=self.team.pk,
            source_id=source.pk,
            table=None,
            should_sync=True,
            status=enabled_schema_status,
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 200
        assert response.json()["status"] == expected_source_status

    def test_delete_external_data_source(self):
        source = self._create_external_data_source()
        schema = self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204

        assert ExternalDataSource.objects.filter(pk=source.pk, deleted=True).exists()
        assert ExternalDataSchema.objects.filter(pk=schema.pk, deleted=True).exists()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.delete_discover_schemas_schedule")
    def test_delete_external_data_source_tears_down_discovery_schedule(self, mock_delete_discover):
        source = self._create_external_data_source()
        self._create_external_data_schema(source.pk)

        response = self.client.delete(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")

        assert response.status_code == 204
        mock_delete_discover.assert_called_once_with(str(source.pk))

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.bulk_delete_external_data_schedules",
        return_value=[("schema-id", Exception("Schema schedule delete failed"))],
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.delete_external_data_schedule",
        side_effect=Exception("External delete failed"),
    )
    def test_delete_external_data_source_soft_deletes_even_if_external_cleanup_fails(
        self, _mock_delete_schedule, _mock_bulk_delete, mock_capture_exception
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
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.trigger_external_data_source_workflow"
    )
    def test_reload_external_data_source(self, mock_trigger):
        source = self._create_external_data_source()

        response = self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/reload/")

        source.refresh_from_db()

        self.assertEqual(mock_trigger.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(source.status, "Running")

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_creates_new_schemas_and_returns_counts(self, mock_get_source):
        parsed_config = Mock(spec=["to_dict"])
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
        self.assertEqual(data["total_tables_seen"], 2)
        self.assertEqual(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).count(), 2
        )
        names = list(
            ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=source.pk, deleted=False).values_list(
                "name", flat=True
            )
        )
        self.assertCountEqual(names, ["table_a", "table_b"])

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_returns_400_when_get_schemas_raises(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_non_retryable_errors.return_value = {"Connection failed": None}
        mock_get_source.return_value.get_schemas.side_effect = Exception("Connection failed")
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Could not fetch schemas from source", response.json().get("message", ""))

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_returns_zero_total_tables_seen_when_source_returns_nothing(self, mock_get_source):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = []
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["added"], 0)
        self.assertEqual(data["deleted"], 0)
        self.assertEqual(data["total_tables_seen"], 0)

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_returns_specific_message_without_capture_for_expected_source_error(
        self, mock_get_source, mock_capture_exception
    ):
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_non_retryable_errors.return_value = {"timeout": None}
        mock_get_source.return_value.get_schemas.side_effect = TimeoutError("connection timed out")
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get("message"),
            "Connection timed out while fetching schemas from the source.",
        )
        mock_capture_exception.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_captures_unexpected_source_error(self, mock_get_source, mock_capture_exception):
        error = RuntimeError("schema parser exploded")
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_non_retryable_errors.return_value = {}
        mock_get_source.return_value.get_schemas.side_effect = error
        source = self._create_external_data_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("message"), "Could not fetch schemas from source.")
        mock_capture_exception.assert_called_once_with(
            error,
            {
                "source_id": str(source.id),
                "source_type": source.source_type,
                "team_id": self.team.pk,
                "refresh_schemas": True,
            },
        )

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.trigger_external_data_source_workflow"
    )
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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
                "created_via": "web",
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
                "created_via": "web",
                "access_method": "direct",
                "prefix": "   ",
                "payload": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"message": "Name is required for direct query sources"})

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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
                "created_via": "web",
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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
                "created_via": "web",
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_direct_postgres_rejects_row_filters(self, mock_get_source):
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
                "created_via": "web",
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
                        {
                            "name": "accounts",
                            "should_sync": True,
                            "sync_type": None,
                            "row_filters": [{"column": "id", "operator": ">", "value": 10}],
                        },
                    ],
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not supported for direct-query sources", str(response.json()))
        self.assertFalse(ExternalDataSource.objects.filter(team_id=self.team.pk).exists())

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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
                "created_via": "web",
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

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.get_primary_key_columns")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cdc_pg_connection")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_cdc_with_blank_schema_uses_physical_schema_metadata(
        self,
        mock_get_source,
        mock_cdc_pg_connection,
        mock_get_primary_key_columns,
        mock_setup_cdc_resources,
        mock_add_table,
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

        def setup_cdc_slot(_adapter, source_model, _payload):
            source_model.job_inputs = {
                **(source_model.job_inputs or {}),
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            }
            source_model.save(update_fields=["job_inputs", "updated_at"])
            return None

        mock_setup_cdc_resources.side_effect = setup_cdc_slot

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
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

        # The adapter reads the publication name from config itself, so the call is just
        # (source, schema, table). The first arg is the source model.
        mock_add_table.assert_called_once()
        assert mock_add_table.call_args.args[1:] == ("analytics", "events")

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.get_primary_key_columns")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cdc_pg_connection")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_cdc_leaves_unenabled_schemas_without_sync_type(
        self,
        mock_get_source,
        mock_cdc_pg_connection,
        mock_get_primary_key_columns,
        mock_setup_cdc_resources,
        mock_add_table,
        _mock_is_cdc_enabled_for_team,
    ):
        # A CDC source discovers every table, but the user only enables a few. Tables the user
        # didn't enable haven't had a sync method set up, so they must be created with a blank
        # sync_type (the schemas UI keys off this to prompt setup). Only the enabled table gets
        # the concrete `cdc` method + config + publication add.
        source_mock = mock_get_source.return_value
        source_mock.validate_config.return_value = (True, [])
        parsed_config = Mock()
        parsed_config.schema = "analytics"
        parsed_config.to_dict.return_value = {
            "host": "localhost",
            "port": 5432,
            "database": "app",
            "user": "user",
            "password": "pass",
            "schema": "analytics",
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
            ),
            SourceSchema(
                name="analytics.sessions",
                supports_incremental=False,
                supports_append=False,
                supports_cdc=True,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="analytics",
                source_table_name="sessions",
            ),
        ]

        mock_cdc_pg_connection.return_value.__enter__.return_value = object()
        mock_cdc_pg_connection.return_value.__exit__.return_value = None
        mock_get_primary_key_columns.return_value = {"events": ["id"]}

        def setup_cdc_resources(_adapter, source_model, _payload):
            source_model.job_inputs = {
                **(source_model.job_inputs or {}),
                "cdc_enabled": True,
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "test_slot",
                "cdc_publication_name": "test_pub",
            }
            source_model.save(update_fields=["job_inputs", "updated_at"])
            return None

        mock_setup_cdc_resources.side_effect = setup_cdc_resources

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "analytics",
                    "cdc_enabled": True,
                    "schemas": [
                        {"name": "analytics.events", "should_sync": True, "sync_type": "cdc"},
                        {"name": "analytics.sessions", "should_sync": False, "sync_type": "cdc"},
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content

        enabled = ExternalDataSchema.objects.get(team_id=self.team.pk, name="analytics.events")
        assert enabled.sync_type == ExternalDataSchema.SyncType.CDC
        assert enabled.sync_type_config["cdc_mode"] == "snapshot"
        assert enabled.sync_type_config["cdc_table_mode"] == "consolidated"

        unenabled = ExternalDataSchema.objects.get(team_id=self.team.pk, name="analytics.sessions")
        assert unenabled.sync_type is None
        assert unenabled.should_sync is False
        # No CDC config noise — just the discovered metadata so column selection still works.
        assert "cdc_mode" not in unenabled.sync_type_config
        assert "cdc_table_mode" not in unenabled.sync_type_config

        # Only the enabled table is added to the replication publication. The adapter reads the
        # publication name from config itself, so the call is just (source, schema, table).
        mock_add_table.assert_called_once()
        assert mock_add_table.call_args.args[1:] == ("analytics", "events")

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.add_table"
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.get_primary_key_columns")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cdc_pg_connection")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_cdc_rejects_table_without_primary_key(
        self,
        mock_get_source,
        mock_cdc_pg_connection,
        mock_get_primary_key_columns,
        mock_setup_cdc_resources,
        mock_add_table,
        _mock_is_cdc_enabled_for_team,
    ):
        # CDC (logical replication) cannot identify rows on UPDATE/DELETE without a primary key.
        # Frontend gates on `supports_cdc`, but the backend must enforce too — direct API/MCP
        # callers, or a UI that lost track of `supports_cdc`, would otherwise create a schema
        # that enters streaming mode and breaks downstream.
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
                name="tracking_link",
                supports_incremental=False,
                supports_append=False,
                supports_cdc=False,
                columns=[("id", "uuid", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="tracking_link",
            )
        ]

        mock_cdc_pg_connection.return_value.__enter__.return_value = object()
        mock_cdc_pg_connection.return_value.__exit__.return_value = None
        # Source DB reports no PK for the table.
        mock_get_primary_key_columns.return_value = {}

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "cdc_enabled": True,
                    "schemas": [
                        {"name": "tracking_link", "should_sync": True, "sync_type": "cdc"},
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "primary key" in response.json()["message"].lower()
        assert "tracking_link" in response.json()["message"]
        # No source row left behind on validation failure.
        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 0
        # CDC slot setup must not run when validation rejects — otherwise we'd leave a
        # replication slot + publication on the source for a config we're about to refuse.
        mock_setup_cdc_resources.assert_not_called()
        mock_add_table.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.get_primary_key_columns")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cdc_pg_connection")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_cdc_returns_400_when_pk_detection_connection_fails(
        self,
        mock_get_source,
        mock_cdc_pg_connection,
        mock_get_primary_key_columns,
        mock_setup_cdc_resources,
        _mock_is_cdc_enabled_for_team,
        mock_capture_exception,
    ):
        # Credential validation connects with sslmode=prefer (falls back to unencrypted), but the
        # CDC primary-key detection connection requires SSL. A database that doesn't support SSL
        # raises SSLRequiredError here — a user/upstream connection problem, not a bug. It must
        # surface as a clean 400, leave no source row behind, and not be captured as error noise.
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
                name="borrower",
                supports_incremental=True,
                supports_append=True,
                supports_cdc=True,
                columns=[("id", "uuid", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="borrower",
            )
        ]

        mock_cdc_pg_connection.return_value.__enter__.side_effect = SSLRequiredError(
            "SSL/TLS connection is required but your database does not support it. "
            "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    "cdc_enabled": True,
                    "schemas": [
                        {"name": "borrower", "should_sync": True, "sync_type": "cdc"},
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "change data capture" in response.json()["message"].lower()
        # No source row left behind on a connection failure.
        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 0
        # CDC slot setup must not run, and the expected connection failure isn't captured as noise.
        mock_get_primary_key_columns.assert_not_called()
        mock_setup_cdc_resources.assert_not_called()
        mock_capture_exception.assert_not_called()

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_rejects_cdc_schemas_when_source_cdc_disabled(
        self,
        mock_get_source,
        mock_setup_cdc_resources,
        _mock_is_cdc_enabled_for_team,
    ):
        # If the user never toggled CDC on at the source-setup step, `payload.cdc_enabled` is
        # False and `_setup_cdc_resources` never runs — so no replication slot/publication exists
        # on the source. Accepting per-schema `sync_type=cdc` in that state would persist
        # broken configs (no slot, empty PKs, snapshot→streaming flip leaving everything
        # Failed). Backend must reject up front.
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
                name="borrower",
                supports_incremental=True,
                supports_append=True,
                supports_cdc=True,
                columns=[("id", "uuid", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="borrower",
            )
        ]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Postgres",
                "created_via": "web",
                "payload": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                    # Note: no cdc_enabled flag here — source-level CDC is off.
                    "schemas": [
                        {"name": "borrower", "should_sync": True, "sync_type": "cdc"},
                    ],
                },
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "cdc must be enabled" in response.json()["message"].lower()
        assert "borrower" in response.json()["message"]
        assert ExternalDataSource.objects.filter(team_id=self.team.pk).count() == 0
        mock_setup_cdc_resources.assert_not_called()

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
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @parameterized.expand(
        [
            # Field omitted -> None: sync everything (default).
            ("omitted_means_sync_all", "omitted", None),
            # Explicit null -> None: also sync everything.
            ("null_means_sync_all", None, None),
            # Explicit empty list -> []: sync only PKs + incremental field. Critical:
            # this must NOT collapse to None, since `[]` and `None` carry different
            # semantics downstream (`build_select_clause`, `filter_columns_by_*`).
            ("empty_list_means_pks_only", [], []),
            # Subset list passes through verbatim.
            ("subset_passes_through", ["email", "name"], ["email", "name"]),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_persists_enabled_columns_payload(
        self,
        _name: str,
        payload_value: list[str] | None | str,
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
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("email", "text", True), ("name", "text", True)],
                foreign_keys=[],
            ),
        ]

        schema_payload: dict[str, t.Any] = {"name": "events", "should_sync": True, "sync_type": None}
        if payload_value != "omitted":
            schema_payload["enabled_columns"] = payload_value

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
                    "schemas": [schema_payload],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, name="events")
        assert schema.enabled_columns == expected_persisted

    @parameterized.expand(
        [
            ("omitted_means_no_masks", "omitted", None),
            ("null_means_no_masks", None, None),
            # Unlike enabled_columns, `[]` and `None` mean the same thing for masks (nothing masked).
            ("empty_list_means_no_masks", [], None),
            # The wizard's mask selections must survive creation — dropping them here means the
            # first sync lands the sensitive column in plaintext.
            ("subset_passes_through", ["email"], ["email"]),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_create_postgres_persists_masked_columns_payload(
        self,
        _name: str,
        payload_value: list[str] | None | str,
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
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False), ("email", "text", True), ("name", "text", True)],
                foreign_keys=[],
            ),
        ]

        schema_payload: dict[str, t.Any] = {"name": "events", "should_sync": True, "sync_type": None}
        if payload_value != "omitted":
            schema_payload["masked_columns"] = payload_value

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
                    "schemas": [schema_payload],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        schema = ExternalDataSchema.objects.get(team_id=self.team.pk, name="events")
        assert schema.masked_columns == expected_persisted

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_renames_legacy_direct_query_rows(self, mock_get_source):
        # Direct-query mode opts in to eager renaming: the live `DataWarehouseTable` is rebuilt
        # from `schema_metadata` on every `refresh_schemas`, so renaming the row never orphans
        # data. This is the long-standing behavior we MUST preserve for direct sources.
        mock_get_source.return_value.parse_config.return_value = None
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(
                name="public.auth_group",
                supports_incremental=False,
                supports_append=False,
                columns=[("id", "integer", False)],
                foreign_keys=[],
                source_schema="public",
                source_table_name="auth_group",
            ),
        ]
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="direct",
            access_method=ExternalDataSource.AccessMethod.DIRECT,
            job_inputs={"host": "localhost", "port": 5432, "schema": "public"},
        )
        legacy_table = DataWarehouseTable.objects.create(
            name="auth_group",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            url_pattern=DIRECT_POSTGRES_URL_PATTERN,
            external_data_source=source,
            columns={"id": {"hogql": "IntegerDatabaseField", "clickhouse": "Int64"}},
        )
        legacy_schema = ExternalDataSchema.objects.create(
            team_id=self.team.pk,
            source_id=source.pk,
            name="auth_group",
            should_sync=True,
            table=legacy_table,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/refresh_schemas/"
        )
        assert response.status_code == status.HTTP_200_OK

        legacy_schema.refresh_from_db()
        # Direct mode renames the row to the qualified discovered name.
        assert legacy_schema.name == "public.auth_group"
        assert legacy_schema.table_id == legacy_table.id

    def test_create_direct_unsupported_source_type_is_rejected(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
                "access_method": "direct",
                "prefix": "Read replica",
                "payload": {},
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"message": "Direct query mode is currently supported only for Postgres, MySQL, and Snowflake sources."},
        )

    def test_source_prefix_rejects_direct_unsupported_source_type(self):
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
            {"message": "Direct query mode is currently supported only for Postgres, MySQL, and Snowflake sources."},
        )

    def test_source_prefix_accepts_direct_mysql(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/source_prefix/",
            data={
                "source_type": "MySQL",
                "access_method": "direct",
                "prefix": "Read replica",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @parameterized.expand(
        [
            # (test name, source_type, supports_xmin, expected_xmin_available)
            ("postgres_capable", "Postgres", True, True),
            ("postgres_not_capable", "Postgres", False, False),
            ("non_postgres", "MySQL", True, None),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_database_schema_xmin_available_gating(
        self, _name, source_type, supports_xmin, expected_xmin_available, mock_get_source
    ):
        # xmin is Postgres-only: the discovery response reports `xmin_available=None` for any other
        # source, regardless of the (erroneous) per-schema `supports_xmin` flag.
        from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource

        source = PostgresSource() if source_type == "Postgres" else MySQLSource()
        mock_get_source.return_value = source

        fake_schema = SourceSchema(
            name="public.accounts",
            supports_incremental=False,
            supports_append=False,
            supports_xmin=supports_xmin,
            columns=[("id", "integer", False)],
            foreign_keys=[],
        )

        with (
            patch.object(source, "validate_credentials_for_access_method", return_value=(True, None)),
            patch.object(source, "get_schemas", return_value=[fake_schema]),
            patch(
                "products.data_warehouse.backend.presentation.views.external_data_source.is_xmin_enabled_for_team",
                return_value=True,
            ),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": source_type,
                    "host": "localhost",
                    "port": 5432,
                    "database": "app",
                    "user": "user",
                    "password": "pass",
                    "schema": "public",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.json()[0]["xmin_available"], expected_xmin_available)

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

    def test_database_schema_unknown_source_type(self):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
            data={"source_type": "GoogleAds-"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["message"] == "Unknown source_type 'GoogleAds-'"

    def test_database_schema_stripe_credentials(self):
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
            ) as validate_credentials_mock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.check_stripe_endpoint_permissions"
            ) as check_perms_mock,
        ):
            validate_credentials_mock.return_value = True
            check_perms_mock.return_value = {}

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "blah"},
                    "stripe_account_id": "blah",
                },
            )

            assert response.status_code == 200
            # Each schema in the response should expose the new permission_error field —
            # mock returns {} so every entry defaults to None (available).
            for entry in response.json():
                assert entry["permission_error"] is None

    def test_database_schema_stripe_credentials_sad_path(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
        ) as validate_credentials_mock:
            from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.stripe import (
                StripePermissionError,
            )

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

    @parameterized.expand(
        [
            ("expected_source_error", False),
            ("unexpected_source_error", True),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_database_schema_captures_only_unexpected_source_errors(
        self, _name, expect_capture, mock_get_source, mock_capture_exception
    ):
        from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.bigquery import (
            BIGQUERY_DATASET_NOT_FOUND_ERROR,
            BigQueryDatasetNotFoundError,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source import BigQuerySource

        error: Exception = (
            RuntimeError("schema discovery exploded")
            if expect_capture
            else BigQueryDatasetNotFoundError(BIGQUERY_DATASET_NOT_FOUND_ERROR)
        )
        source = BigQuerySource()
        mock_get_source.return_value = source

        with (
            patch.object(source, "validate_config", return_value=(True, [])),
            patch.object(source, "parse_config", return_value=None),
            patch.object(source, "validate_credentials", return_value=(True, None)),
            patch.object(source, "get_schemas", side_effect=error),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={"source_type": "BigQuery"},
            )

        assert response.status_code == 400
        if expect_capture:
            # Unexpected errors return the safe generic fallback, never the raw exception string.
            assert response.json()["message"] == "Could not fetch schemas from source."
            mock_capture_exception.assert_called_once_with(error, {"source_type": "BigQuery", "team_id": self.team.pk})
        else:
            # Expected per-source errors surface the classifier's friendly copy.
            assert response.json()["message"] == str(error)
            mock_capture_exception.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_database_schema_rejects_source_without_schema_discovery(self, mock_get_source, mock_capture_exception):
        # AmazonS3 deliberately omits get_schemas, so the base raises NotImplementedError. The endpoint
        # must return a clean 400 without capturing it as a server error, mirroring `setup`.
        from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_s3.source import AmazonS3Source

        source = AmazonS3Source()
        mock_get_source.return_value = source

        with (
            patch.object(source, "validate_config", return_value=(True, [])),
            patch.object(source, "parse_config", return_value=None),
            patch.object(source, "validate_credentials", return_value=(True, None)),
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={"source_type": "AmazonS3"},
            )

        assert response.status_code == 400
        assert response.json()["message"] == "Source type 'AmazonS3' does not support schema discovery."
        mock_capture_exception.assert_not_called()

    def test_database_schema_stripe_surfaces_per_endpoint_permission_errors(self):
        """Schema-selection step calls get_endpoint_permissions and merges the per-endpoint
        result into each schema row so the UI can disable tables the credentials can't reach."""
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
            ) as validate_credentials_mock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.check_stripe_endpoint_permissions"
            ) as check_perms_mock,
        ):
            validate_credentials_mock.return_value = True
            # Mark Charge as denied; everything else implicitly returns None via .get()
            check_perms_mock.return_value = {"Charge": "Missing rak_charge_read"}

            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/database_schema/",
                data={
                    "source_type": "Stripe",
                    "auth_method": {"selection": "api_key", "stripe_secret_key": "blah"},
                    "stripe_account_id": "blah",
                },
            )

            assert response.status_code == 200
            by_table = {entry["table"]: entry for entry in response.json()}
            assert by_table["Charge"]["permission_error"] == "Missing rak_charge_read"
            assert by_table["Customer"]["permission_error"] is None

    def test_database_schema_zendesk_credentials(self):
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials"
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials"
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.validate_stripe_credentials"
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_database_schema_does_not_request_row_counts(self, mock_get_source):
        parsed_config = Mock()
        mock_source = mock_get_source.return_value
        mock_source.validate_config.return_value = (True, [])
        mock_source.parse_config.return_value = parsed_config
        mock_source.validate_credentials.return_value = (True, None)
        mock_source.get_schemas.return_value = [
            SourceSchema(name="table_1", supports_incremental=False, supports_append=False, row_count=42)
        ]
        mock_source.get_endpoint_permissions.return_value = {}

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_foreign_keys",
        return_value={},
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_primary_key_columns",
        return_value={},
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.pg_connection")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_row_count")
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
                        {
                            "label": "id",
                            "type": "integer",
                            "field": "id",
                            "field_type": "integer",
                            "nullable": True,
                            # Index lookup raises against the mocked pg_connection (object())
                            # and falls back to the no-warning default (is_indexed=True).
                            "is_indexed": True,
                        }
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "cdc_available": None,
                    "xmin_available": None,
                    "incremental_field": "id",
                    "sync_type": None,
                    "supports_webhooks": False,
                    "webhook_only": False,
                    "available_columns": [
                        {"field": "id", "label": "id", "type": "integer", "nullable": True},
                    ],
                    "detected_primary_keys": ["id"],
                    "permission_error": None,
                    "rls_warning": None,
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
                        {
                            "label": "id",
                            "type": "integer",
                            "field": "id",
                            "field_type": "integer",
                            "nullable": True,
                            # Index lookup raises against the mocked pg_connection (object())
                            # and falls back to the no-warning default (is_indexed=True).
                            "is_indexed": True,
                        }
                    ],
                    "incremental_available": True,
                    "append_available": True,
                    "cdc_available": None,
                    "xmin_available": None,
                    "incremental_field": "id",
                    "sync_type": None,
                    "supports_webhooks": False,
                    "webhook_only": False,
                    "available_columns": [
                        {"field": "id", "label": "id", "type": "integer", "nullable": True},
                    ],
                    "detected_primary_keys": ["id"],
                    "permission_error": None,
                    "rls_warning": None,
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.get_postgres_schemas",
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
            "created_via": "web",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_trimming_payload(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Stripe",
                "created_via": "web",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ) as mock_validate_credentials:
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{str(source.pk)}/",
                data={
                    "job_inputs": {
                        # Adding an SSH tunnel requires re-supplying the database password.
                        "password": "password",
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
                        },
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
                    "database": "other_db",
                    "password": None,  # Frontend sends null
                },
            },
        )

        assert response.status_code == 200

        # Verify password was preserved, not overwritten with null
        source.refresh_from_db()
        assert source.job_inputs["database"] == "other_db"  # Database was updated
        assert source.job_inputs["password"] == "original_password"  # Password preserved
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
                    "database": "other_db",
                    "password": "",  # Frontend sends empty string when user doesn't enter new password
                },
            },
        )

        assert response.status_code == 200

        # Verify password was preserved, not overwritten with empty string
        source.refresh_from_db()
        assert source.job_inputs["database"] == "other_db"  # Database was updated
        assert source.job_inputs["password"] == "original_password"  # Password preserved
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_host_change_without_credentials_is_rejected(self, mock_validate_credentials):
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

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        source.refresh_from_db()
        assert source.job_inputs["host"] == "db.example.com"
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_with_host_change_and_credentials_succeeds(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_host_with_creds",
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
                    "password": "new_password",
                },
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"
        assert source.job_inputs["password"] == "new_password"
        mock_validate_credentials.assert_called_once()

    @parameterized.expand([("with_password", {"password": "new_password"}, 200), ("without_password", {}, 400)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_host_change_with_stored_connection_string(
        self, _name, extra_creds, expected_status, mock_validate_credentials
    ):
        # A stored `connection_string` (never re-suppliable via the edit form) must not block a host
        # change, while `password` stays gated: re-entering it succeeds, omitting it is still rejected.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_host_conn_string",
            job_inputs={
                "source_type": "Postgres",
                "connection_string": "postgresql://dbuser:original_password@db.example.com:5432/mydb",
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
            data={"job_inputs": {"host": "new-host.example.com", **extra_creds}},
        )

        assert response.status_code == expected_status, response.json()
        assert ("re-entering your credentials" in str(response.json())) == (expected_status == 400)
        source.refresh_from_db()
        # Preserved by the merge regardless of outcome — connection-string-based sources rely on this.
        assert (
            source.job_inputs["connection_string"] == "postgresql://dbuser:original_password@db.example.com:5432/mydb"
        )
        if expected_status == 200:
            assert source.job_inputs["host"] == "new-host.example.com"
            assert source.job_inputs["password"] == "new_password"
            mock_validate_credentials.assert_called_once()
        else:
            assert source.job_inputs["host"] == "db.example.com"
            assert source.job_inputs["password"] == "original_password"
            mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source.FreshdeskSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_freshdesk_subdomain_change_without_api_key_is_rejected(self, mock_validate_credentials):
        # Freshdesk's connection target is `subdomain`, not `host`. Changing it without re-supplying
        # the API key must be rejected so the stored key can't be redirected to another tenant.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Freshdesk",
            created_by=self.user,
            prefix="test_freshdesk_subdomain",
            job_inputs={"source_type": "Freshdesk", "subdomain": "acme", "api_key": "original_key"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"subdomain": "attacker"}},
        )

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        source.refresh_from_db()
        assert source.job_inputs["subdomain"] == "acme"
        assert source.job_inputs["api_key"] == "original_key"
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.source.FreshdeskSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_freshdesk_subdomain_change_with_api_key_succeeds(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Freshdesk",
            created_by=self.user,
            prefix="test_freshdesk_subdomain_creds",
            job_inputs={"source_type": "Freshdesk", "subdomain": "acme", "api_key": "original_key"},
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"subdomain": "newco", "api_key": "new_key"}},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["subdomain"] == "newco"
        assert source.job_inputs["api_key"] == "new_key"
        mock_validate_credentials.assert_called_once()

    def _servicenow_source(self) -> ExternalDataSource:
        # ServiceNow's connection target is `instance_url` (not a top-level `host`) and its
        # secret lives nested inside the `auth_method` container.
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="ServiceNow",
            created_by=self.user,
            prefix="servicenow_src",
            job_inputs={
                "instance_url": "https://acme.service-now.com",
                "auth_method": {"selection": "api_key", "api_key": "sk_existing"},
            },
        )

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.ServiceNowSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_servicenow_instance_url_change_without_credentials_is_rejected(self, mock_validate_credentials):
        source = self._servicenow_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"instance_url": "https://attacker.example.com"}},
        )

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        source.refresh_from_db()
        assert source.job_inputs["instance_url"] == "https://acme.service-now.com"
        assert source.job_inputs["auth_method"]["api_key"] == "sk_existing"
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source.ServiceNowSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_servicenow_instance_url_change_with_credentials_succeeds(self, mock_validate_credentials):
        source = self._servicenow_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "instance_url": "https://new-instance.service-now.com",
                    "auth_method": {"selection": "api_key", "api_key": "sk_new"},
                },
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["instance_url"] == "https://new-instance.service-now.com"
        assert source.job_inputs["auth_method"]["api_key"] == "sk_new"
        mock_validate_credentials.assert_called_once()

    def _custom_source(self, base_url: str, resource_paths: list[str] | None = None) -> ExternalDataSource:
        paths = resource_paths if resource_paths is not None else ["/users"]
        manifest = {
            "client": {"base_url": base_url, "auth": {"type": "api_key", "name": "key", "location": "query"}},
            "resources": [{"name": f"resource_{i}", "endpoint": {"path": p}} for i, p in enumerate(paths)],
        }
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Custom",
            created_by=self.user,
            prefix="custom_src",
            job_inputs={"manifest_json": json.dumps(manifest), "auth_api_key": "sk_existing"},
        )

    @parameterized.expand([("without_credentials", {}, 400), ("with_credentials", {"auth_api_key": "sk_new"}, 200)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_manifest_host_change(
        self, _name, extra_creds, expected_status, mock_validate_credentials
    ):
        # The custom source's host lives inside the manifest. Retargeting it to a new host requires
        # re-supplying the secret; without it the preserved credential would reach a server the editor
        # chose, so the change is rejected and nothing is persisted.
        source = self._custom_source("https://api.example.com")
        new_manifest = {
            "client": {
                "base_url": "https://attacker.example.net",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest), **extra_creds}},
        )

        assert response.status_code == expected_status, response.json()
        assert ("re-entering your credentials" in str(response.json())) == (expected_status == 400)
        source.refresh_from_db()
        persisted_host = "attacker.example.net" if expected_status == 200 else "api.example.com"
        assert persisted_host in source.job_inputs["manifest_json"]
        # The credential probe only runs once the re-entry gate has passed.
        assert mock_validate_credentials.called == (expected_status == 200)

    def _custom_oauth2_source(self, token_url: str) -> ExternalDataSource:
        manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "oauth2", "client_id": "cid", "token_url": token_url},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Custom",
            created_by=self.user,
            prefix="custom_oauth2",
            job_inputs={"manifest_json": json.dumps(manifest), "auth_oauth2_client_secret": "cs_existing"},
        )

    @parameterized.expand(
        [("without_credentials", {}, 400), ("with_credentials", {"auth_oauth2_client_secret": "cs_new"}, 200)]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_oauth2_token_url_change_requires_reentry(
        self, _name, extra_creds, expected_status, mock_validate_credentials
    ):
        # The OAuth2 token endpoint receives the stored client_secret. Repointing token_url to a new
        # host without re-supplying the secret would exfiltrate it to a server the editor chose — so it
        # is gated exactly like a base_url change. This is the net-new credential-redirect coverage that
        # the Smokescreen egress proxy structurally cannot provide.
        source = self._custom_oauth2_source("https://auth.example.com/oauth2/token")
        new_manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "oauth2", "client_id": "cid", "token_url": "https://attacker.example.net/token"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest), **extra_creds}},
        )

        assert response.status_code == expected_status, response.json()
        assert ("re-entering your credentials" in str(response.json())) == (expected_status == 400)
        # The credential probe only runs once the re-entry gate has passed.
        assert mock_validate_credentials.called == (expected_status == 200)

    def _custom_oauth2_integration_source(self) -> ExternalDataSource:
        manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "oauth2", "client_id": "cid", "token_url": "https://auth.example.com/token"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Custom",
            created_by=self.user,
            prefix="custom_oauth2_int",
            job_inputs={
                "manifest_json": json.dumps(manifest),
                "auth_oauth2_integration_id": "11111111-1111-1111-1111-111111111111",
            },
        )

    @parameterized.expand(
        [
            ("no_reentry", {}, 400),
            ("partial_reentry", {"auth_oauth2_client_secret": "cs_new"}, 400),
            (
                "full_reentry",
                {"auth_oauth2_client_secret": "cs_new", "auth_oauth2_refresh_token": "rt_new"},
                200,
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_oauth2_row_backed_source_host_change_requires_full_reentry(
        self, _name, extra_inputs, expected_status, mock_validate_credentials
    ):
        # A row-backed OAuth2 source keeps no secret in job_inputs — the token lives in the bound
        # CustomOAuth2Integration row and is injected at sync time. A manifest host change would still
        # redirect the row's injected token, so the gate fires unless the editor re-enters every secret
        # the row holds (which validation then rotates into the row) — a partial re-entry still
        # preserves a secret the editor may not know.
        source = self._custom_oauth2_integration_source()
        CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            external_data_source=source,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token"},
            sensitive_config={"client_secret": "cs", "refresh_token": "rt"},
        )
        new_manifest = {
            "client": {
                "base_url": "https://attacker.example.net",
                "auth": {"type": "oauth2", "client_id": "cid", "token_url": "https://auth.example.com/token"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest), **extra_inputs}},
        )

        assert response.status_code == expected_status, response.json()
        assert ("re-entering your credentials" in str(response.json())) == (expected_status == 400)
        assert mock_validate_credentials.called == (expected_status == 200)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_oauth2_source_cannot_clear_pointer_to_move_host_while_bound(self, mock_validate_credentials):
        # Bypass guard: clearing auth_oauth2_integration_id does not unbind the CustomOAuth2Integration row,
        # so an editor must not be able to clear the pointer, move the manifest host, then re-add the pointer
        # to redirect the still-bound token. A row bound to the source makes the host-change gate fire even
        # when job_inputs currently omits the pointer.
        source = self._custom_oauth2_integration_source()
        CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            external_data_source=source,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token"},
            sensitive_config={"client_secret": "s"},
        )
        new_manifest = {
            "client": {
                "base_url": "https://attacker.example.net",
                "auth": {"type": "oauth2", "client_id": "cid", "token_url": "https://auth.example.com/token"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest), "auth_oauth2_integration_id": ""}},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "re-entering your credentials" in str(response.json())
        mock_validate_credentials.assert_not_called()

    def _valid_oauth2_manifest(self) -> dict:
        return {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/token",
                    "grant_type": "refresh_token",
                },
            },
            "resources": [
                {"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "data"}}
            ],
        }

    def _mock_oauth2_network(self, mock_token_session, mock_probe_session) -> None:
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.raw.read.return_value = json.dumps(
            {"access_token": "minted-AT", "expires_in": 3600, "refresh_token": "rotated-RT"}
        ).encode()
        mock_token_session.return_value.post.return_value = token_response
        mock_probe_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.trigger_external_data_source_workflow"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
    )
    def test_create_custom_oauth2_source_adopts_secrets_into_bound_row(
        self, mock_token_session, mock_probe_session, _mock_trigger
    ):
        # The whole flow through the real create endpoint: secrets typed on the source config screen
        # end up in a CustomOAuth2Integration row bound to the new source, and the persisted
        # job_inputs carry only the server-written pointer — never the raw secrets. A client-supplied
        # pointer is dropped, so it cannot pre-seed the adoption.
        self._mock_oauth2_network(mock_token_session, mock_probe_session)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Custom",
                "prefix": "customoauth_",
                "payload": {
                    "manifest_json": json.dumps(self._valid_oauth2_manifest()),
                    "auth_oauth2_client_secret": "cs",
                    "auth_oauth2_refresh_token": "orig-RT",
                    "auth_oauth2_integration_id": "22222222-2222-2222-2222-222222222222",
                    "schemas": [{"name": "users", "should_sync": True, "sync_type": "full_refresh"}],
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).get()
        assert source.job_inputs["auth_oauth2_integration_id"] == str(row.pk)
        assert not source.job_inputs.get("auth_oauth2_client_secret")
        assert not source.job_inputs.get("auth_oauth2_refresh_token")
        assert row.external_data_source_id == source.pk
        assert row.created_by_id == self.user.pk
        assert row.sensitive_config["client_secret"] == "cs"
        assert row.sensitive_config["refresh_token"] == "rotated-RT"

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.trigger_external_data_source_workflow"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
    )
    def test_setup_custom_oauth2_source_stores_pointer_not_secrets(
        self, mock_token_session, mock_probe_session, _mock_trigger
    ):
        # `setup` validates first and then re-parses the raw payload with the credential gate skipped —
        # the adoption rewrite must be propagated onto that payload, or the created source would keep
        # the raw secrets in job_inputs and orphan the row.
        self._mock_oauth2_network(mock_token_session, mock_probe_session)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={
                "source_type": "Custom",
                "prefix": "customoauthsetup_",
                "payload": {
                    "manifest_json": json.dumps(self._valid_oauth2_manifest()),
                    "auth_oauth2_client_secret": "cs",
                    "auth_oauth2_refresh_token": "orig-RT",
                },
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).get()
        assert source.job_inputs["auth_oauth2_integration_id"] == str(row.pk)
        assert not source.job_inputs.get("auth_oauth2_client_secret")
        assert not source.job_inputs.get("auth_oauth2_refresh_token")
        assert row.external_data_source_id == source.pk

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth.make_tracked_session"
    )
    def test_update_reenters_oauth2_secrets_into_bound_row(self, mock_token_session, mock_probe_session):
        # Reconnect happens on the source config screen: re-entered secrets must land in the bound row
        # (not in job_inputs) via the update path's re-serialization.
        self._mock_oauth2_network(mock_token_session, mock_probe_session)
        manifest = self._valid_oauth2_manifest()
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Custom",
            created_by=self.user,
            prefix="customoauthreconnect_",
            job_inputs={"manifest_json": json.dumps(manifest)},
        )
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            created_by=self.user,
            external_data_source=source,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token", "grant_type": "refresh_token"},
            sensitive_config={"client_secret": "old-cs", "refresh_token": "old-rt"},
        )
        source.job_inputs["auth_oauth2_integration_id"] = str(row.pk)
        source.save(update_fields=["job_inputs"])

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "manifest_json": json.dumps(manifest),
                    "auth_oauth2_client_secret": "new-cs",
                    "auth_oauth2_refresh_token": "new-rt",
                }
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        source.refresh_from_db()
        row.refresh_from_db()
        assert source.job_inputs["auth_oauth2_integration_id"] == str(row.pk)
        assert not source.job_inputs.get("auth_oauth2_client_secret")
        assert not source.job_inputs.get("auth_oauth2_refresh_token")
        assert row.sensitive_config["client_secret"] == "new-cs"
        # Validation minted with the re-entered token and persisted the provider's rotation.
        assert mock_token_session.return_value.post.call_args.kwargs["data"]["refresh_token"] == "new-rt"
        assert row.sensitive_config["refresh_token"] == "rotated-RT"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_cannot_repoint_oauth2_integration_id(self, _mock_validate_credentials):
        # The pointer is server-managed: an editor submitting a different integration UUID must have it
        # pinned back to the stored one, or they could route another row's credentials to this source.
        source = self._custom_oauth2_integration_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {"auth_oauth2_integration_id": "33333333-3333-3333-3333-333333333333"},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        source.refresh_from_db()
        assert source.job_inputs["auth_oauth2_integration_id"] == "11111111-1111-1111-1111-111111111111"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_ambiguous_authority_host_change_is_rejected(self, mock_validate_credentials):
        # `https://attacker\@api.example.com/` connects to `attacker` (urllib3/WHATWG) but parses as
        # `api.example.com` under naive urlparse — the guard must see the real host and require re-entry.
        source = self._custom_source("https://api.example.com")
        new_manifest = {
            "client": {
                "base_url": "https://attacker.example.net\\@api.example.com/",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest)}},
        )

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_same_host_manifest_edit_keeps_credentials(self, mock_validate_credentials):
        # Editing a manifest without introducing a new host (e.g. tweaking a path) must not force
        # the user to re-enter the credential — the destination is unchanged.
        source = self._custom_source("https://api.example.com")
        new_manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/v2/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest)}},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["auth_api_key"] == "sk_existing"
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_path_param_host_injection_is_rejected(self, mock_validate_credentials):
        # The new host is hidden in a path-param value (resolved into the path at sync time), not the
        # literal path — the guard must still detect it and require re-entry.
        source = self._custom_source("https://api.example.com")
        new_manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [
                {
                    "name": "users",
                    "endpoint": {"path": "{target}", "params": {"target": "https://attacker.example.net/"}},
                }
            ],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest)}},
        )

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_adding_cross_host_resource_is_rejected(self, mock_validate_credentials):
        # base_url is unchanged, but a resource now points at a brand-new host — the credential would
        # reach a destination it wasn't going to before, so re-entry is still required.
        source = self._custom_source("https://api.example.com")
        new_manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [
                {"name": "users", "endpoint": {"path": "/users"}},
                {"name": "leak", "endpoint": {"path": "https://attacker.example.net/data"}},
            ],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest)}},
        )

        assert response.status_code == 400
        assert "re-entering your credentials" in str(response.json())
        mock_validate_credentials.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_custom_source_removing_host_does_not_require_credentials(self, mock_validate_credentials):
        # Dropping a resource removes a destination host. That can't leak the credential anywhere new,
        # so it must not force the user to re-enter it.
        source = self._custom_source("https://api.example.com", resource_paths=["/users", "https://cdn.other.net/data"])
        new_manifest = {
            "client": {
                "base_url": "https://api.example.com",
                "auth": {"type": "api_key", "name": "key", "location": "query"},
            },
            "resources": [{"name": "users", "endpoint": {"path": "/users"}}],
        }

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"manifest_json": json.dumps(new_manifest)}},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["auth_api_key"] == "sk_existing"
        mock_validate_credentials.assert_called_once()

    def _okta_source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Okta",
            created_by=self.user,
            prefix="okta_src",
            job_inputs={"okta_domain": "company.okta.com", "api_key": "existing_token"},
        )

    @parameterized.expand([("without_token", {}, 400), ("with_token", {"api_key": "new_token"}, 200)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.okta.source.OktaSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_okta_source_domain_change_requires_token(
        self, _name, extra_creds, expected_status, mock_validate_credentials
    ):
        # `okta_domain` is the connection target for Okta. Retargeting it without re-supplying the API
        # token would send the preserved token to a host the editor chose, so the change is rejected.
        source = self._okta_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"okta_domain": "attacker.example.com", **extra_creds}},
        )

        assert response.status_code == expected_status, response.json()
        assert ("re-entering your credentials" in str(response.json())) == (expected_status == 400)
        source.refresh_from_db()
        expected_domain = "attacker.example.com" if expected_status == 200 else "company.okta.com"
        assert source.job_inputs["okta_domain"] == expected_domain
        assert source.job_inputs["api_key"] == ("new_token" if expected_status == 200 else "existing_token")
        # The credential probe only runs once the re-entry gate has passed.
        assert mock_validate_credentials.called == (expected_status == 200)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.okta.source.OktaSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_okta_source_same_domain_keeps_token(self, mock_validate_credentials):
        # Re-saving the source without changing the domain must not force the user to re-enter the token.
        source = self._okta_source()

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"okta_domain": "company.okta.com"}},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["api_key"] == "existing_token"
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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

        # Update without providing ssh_tunnel — include password since host is changing
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "host": "new-host.example.com",
                    "password": "new_password",
                },
            },
        )

        # Should not crash with AttributeError: 'NoneType' object has no attribute 'setdefault'
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"

        source.refresh_from_db()
        assert source.job_inputs["host"] == "new-host.example.com"
        assert source.job_inputs["password"] == "new_password"
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
        # Host change without re-entering credentials is rejected before SSRF check
        assert "re-entering your credentials" in str(response.json())

        source.refresh_from_db()
        assert source.job_inputs["host"] == "db.example.com"

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_update_blocks_internal_host_with_credentials(self):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_internal_host_with_creds",
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
                    "password": "new_password",
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.SourceRegistry.get_source")
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(True, None),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={
                    "job_inputs": {
                        # Disabling the SSH tunnel is an SSH tunnel change — DB password must be re-supplied.
                        "password": "db_password",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
            return_value=(False, "Mocked credentials failure"),
        ):
            response = self.client.patch(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
                data={
                    "job_inputs": {
                        # Re-supply DB password so the failure comes from the mocked credential check below.
                        "password": "db_password",
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

    def test_update_source_with_ssh_tunnel_host_change_without_auth_is_rejected(self):
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

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    # DB password is re-supplied; SSH auth is missing so SSH credential check fails.
                    "password": "db_password",
                    "ssh_tunnel": {
                        "enabled": True,
                        "host": "new-ssh.example.com",
                        "port": 22,
                    },
                },
            },
        )

        assert response.status_code == 400
        assert "SSH tunnel host" in str(response.json())
        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["host"] == "ssh.example.com"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_source_with_ssh_tunnel_host_change_and_auth_succeeds(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_ssh_host_with_auth",
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
                        "password": "old_ssh_password",
                    },
                },
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    # Changing the SSH tunnel forces re-entry of the database password.
                    "password": "db_password",
                    "ssh_tunnel": {
                        "enabled": True,
                        "host": "new-ssh.example.com",
                        "port": 22,
                        "auth": {
                            "selection": "password",
                            "username": "sshuser",
                            "password": "new_ssh_password",
                        },
                    },
                },
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["host"] == "new-ssh.example.com"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "new_ssh_password"
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_source_with_ssh_tunnel_same_host_preserves_auth(self, mock_validate_credentials):
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_ssh_same_host",
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
                    },
                },
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    # Changing any SSH tunnel field forces re-entry of the database password.
                    "password": "db_password",
                    "ssh_tunnel": {
                        "enabled": True,
                        "host": "ssh.example.com",
                        "port": 2222,
                    },
                },
            },
        )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"
        mock_validate_credentials.assert_called_once()

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
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
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

    def test_update_source_ssh_tunnel_change_requires_db_password_reentry(self):
        """VERIA-311: any change to ssh_tunnel must force the database password to be re-supplied,
        otherwise an editor could inject a tunnel that exfiltrates the stored credentials."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_veria_311",
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
                    },
                },
            },
        )

        # Editor swaps the SSH tunnel for an attacker-controlled one without re-entering the DB password.
        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "ssh_tunnel": {
                        "enabled": True,
                        "host": "attacker.example.com",
                        "port": 22,
                        "auth": {
                            "selection": "password",
                            "username": "sshuser",
                            "password": "attacker_password",
                        },
                    },
                },
            },
        )

        assert response.status_code == 400
        assert "database credentials" in str(response.json())

        source.refresh_from_db()
        assert source.job_inputs["ssh_tunnel"]["host"] == "ssh.example.com"
        assert source.job_inputs["password"] == "db_password"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_source_ssh_tunnel_disabled_string_vs_bool_no_false_positive(self, mock_validate_credentials):
        """Regression: stored `enabled: "False"` must compare equal to incoming JSON `false`.

        A naive `str(value or "")` collapses falsy values to "", so stored "False" would diverge
        from incoming False and spuriously demand a password re-entry on every save.
        """
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_disabled_false_string",
            job_inputs={
                "source_type": "Postgres",
                "host": "db.example.com",
                "port": "5432",
                "database": "mydb",
                "user": "dbuser",
                "password": "db_password",
                "schema": "public",
                "ssh_tunnel": {
                    "enabled": "False",
                    "host": "ssh.example.com",
                    "port": "22",
                    "auth": {
                        "type": "password",
                        "username": "sshuser",
                        "password": "ssh_secret_password",
                    },
                },
            },
        )

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={
                "job_inputs": {
                    "database": "renamed_db",
                    "ssh_tunnel": {
                        "enabled": False,
                        "host": "ssh.example.com",
                        "port": 22,
                    },
                },
            },
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["database"] == "renamed_db"
        assert source.job_inputs["password"] == "db_password"
        mock_validate_credentials.assert_called_once()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.validate_credentials",
        return_value=(True, None),
    )
    def test_update_source_ssh_tunnel_no_change_does_not_require_db_password(self, mock_validate_credentials):
        """Re-submitting the same ssh_tunnel (e.g. when saving an unrelated field after a GET) must
        NOT force the user to re-enter the database password — that would break the no-op save path."""
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Postgres",
            created_by=self.user,
            prefix="test_no_change",
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
                    },
                },
            },
        )

        get_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}")
        assert get_response.status_code == 200
        ssh_tunnel_from_get = get_response.json()["job_inputs"]["ssh_tunnel"]

        response = self.client.patch(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/",
            data={"job_inputs": {"ssh_tunnel": ssh_tunnel_from_get, "database": "renamed_db"}},
        )

        assert response.status_code == 200, response.json()
        source.refresh_from_db()
        assert source.job_inputs["database"] == "renamed_db"
        assert source.job_inputs["password"] == "db_password"
        assert source.job_inputs["ssh_tunnel"]["auth"]["password"] == "ssh_secret_password"
        mock_validate_credentials.assert_called_once()

    def test_snowflake_auth_type_create_and_update(self):
        """Test that we can create and update the auth type for a Snowflake source"""
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source.SnowflakeSource.validate_credentials",
                return_value=(True, None),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake.SnowflakeImplementation.connect"
            ) as mocked_connect,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake.SnowflakeImplementation.get_columns",
                return_value={"my_table": [("something", "DATE", False)]},
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake.SnowflakeImplementation.get_primary_keys",
                return_value={"my_table": None},
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.snowflake.SnowflakeImplementation.get_leading_index_columns",
                return_value={"my_table": set()},
            ),
        ):
            mocked_connect.return_value.__enter__.return_value = MagicMock()
            # Create a Snowflake source with password auth
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "prefix": "",
                    "created_via": "web",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.snowflake.source.SnowflakeSource.validate_credentials",
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
                return_value=(True, None),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.get_schemas",
                return_value=[
                    SourceSchema(
                        name="my_table",
                        supports_incremental=False,
                        supports_append=False,
                        columns=[("something", "DATE", False)],
                    )
                ],
            ),
        ):
            # Create a BigQuery source
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/",
                data={
                    "prefix": "",
                    "created_via": "web",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
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
            "products.warehouse_sources.backend.temporal.data_imports.sources.bigquery.source.BigQuerySource.validate_credentials",
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

    @parameterized.expand(
        [
            # name, query string, expected source-type keys (None = unfiltered, expect full catalog)
            ("unfiltered", "", None),
            ("single_type", "?source_type=Stripe", {"Stripe"}),
            ("multi_type", "?source_type=Stripe,Postgres", {"Stripe", "Postgres"}),
        ]
    )
    def test_get_wizard_sources_filtered_by_source_type(self, _name, query, expected_keys):
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/wizard{query}")
        assert response.status_code == 200
        if expected_keys is None:
            assert len(response.json()) > 2  # sanity: unfiltered returns the full catalog
        else:
            assert set(response.json().keys()) == expected_keys

    def test_get_wizard_sources_unknown_source_type_returns_400(self):
        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/wizard?source_type=NotARealSource"
        )
        assert response.status_code == 400
        assert "NotARealSource" in response.json()["message"]

    @parameterized.expand(
        [
            # name, endpoint suffix, body
            ("create", "", {"source_type": "Stripe", "payload": {"stripe_secret_key": {"secretRef": "ref-123"}}}),
            ("setup", "setup/", {"source_type": "Stripe", "payload": {"stripe_secret_key": {"secretRef": "ref-123"}}}),
            (
                "database_schema",
                "database_schema/",
                {"source_type": "Postgres", "password": {"secretRef": "ref-123"}, "host": "db.example.com"},
            ),
        ]
    )
    def test_unresolved_secret_ref_rejected(self, _name, suffix, body):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{suffix}",
            data=body,
            format="json",
        )
        assert response.status_code == 400
        assert "secretRef" in response.json()["message"]

    @parameterized.expand(
        [
            # name, seed sources soft-deleted?, seed for a different team?, expect the limit error
            ("active_sources_at_limit", False, False, True),
            ("soft_deleted_excluded", True, False, False),
            ("other_team_excluded", False, True, False),
        ]
    )
    def test_create_custom_source_per_team_limit(self, _name, deleted, other_team, expect_blocked):
        seed_team_id = self.team.pk
        if other_team:
            seed_team_id = Team.objects.create(organization=self.organization, name="other team").pk

        for i in range(MAX_CUSTOM_SOURCES_PER_TEAM):
            ExternalDataSource.objects.create(
                team_id=seed_team_id,
                source_id=str(uuid.uuid4()),
                connection_id=str(uuid.uuid4()),
                destination_id=str(uuid.uuid4()),
                source_type="Custom",
                prefix=f"custom_{i}_",
                job_inputs={"manifest_json": "{}"},
                deleted=deleted,
            )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/",
            data={
                "source_type": "Custom",
                "prefix": "custom_new_",
                "payload": {"manifest_json": "{}"},
            },
        )

        # Every case 400s; only the at-limit case is blocked *by the per-team limit* — the
        # excluded cases stay under the limit and fail later on the (empty) manifest instead.
        limit_message = f"You can create at most {MAX_CUSTOM_SOURCES_PER_TEAM} custom sources per project."
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        if expect_blocked:
            assert response.json()["message"] == limit_message
        else:
            assert response.json()["message"] != limit_message

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
                        "created_via": "web",
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
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
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
                        "created_via": "web",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookCreationResult

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
        from products.cdp.backend.models.hog_function_template import HogFunctionTemplate

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

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_success(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result()
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
            RESOURCE_TO_STRIPE_OBJECT_TYPE,
        )

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

    def test_create_webhook_no_job_inputs(self):
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

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_external_creation_fails(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result(success=False, error="Permission denied")
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_create_webhook_url_uses_cloud_deployment(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result()
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["webhook_url"].startswith("https://webhooks.us.posthog.com")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    @override_settings(CLOUD_DEPLOYMENT=None, SITE_URL="https://my.posthog.instance")
    def test_create_webhook_url_uses_site_url_for_self_hosted(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result()
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["webhook_url"].startswith("https://my.posthog.instance")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_merges_schemas_on_update(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result()
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
            RESOURCE_TO_STRIPE_OBJECT_TYPE,
        )

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

    def test_create_webhook_template_not_in_db(self):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "sync_hog_function_templates" in response.json()["message"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_saves_extra_inputs(self, mock_create_webhook):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs(self, mock_create_webhook, mock_inputs_updated):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        mock_create_webhook.return_value = self._webhook_result()
        mock_inputs_updated.return_value = (True, None)

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

        # The source should be notified so it can apply the new inputs (e.g.
        # Customer.io enables the reporting webhook once the signing secret arrives).
        mock_inputs_updated.assert_called_once()
        call_args = mock_inputs_updated.call_args
        assert call_args.args[1].endswith(f"/public/webhooks/dwh/{hog_function.id}")
        assert call_args.args[2] == self.team.pk
        assert call_args.args[3] == {"signing_secret": "whsec_manual123"}

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs_propagates_failure_from_source(self, mock_create_webhook, mock_inputs_updated):
        # If the source's webhook_inputs_updated reports failure (e.g. Customer.io
        # rejects the request to enable the webhook), surface that to the caller as
        # a 400 instead of returning 200 + success=true while the webhook stays
        # disabled on the external service.
        mock_create_webhook.return_value = self._webhook_result()
        mock_inputs_updated.return_value = (False, "Customer.io rejected the App API Key (401).")

        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_bad"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body = response.json()
        assert body["success"] is False
        assert "Customer.io rejected" in body["error"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    def test_update_webhook_inputs_requires_job_inputs(self, mock_inputs_updated):
        # Sources persisted without job_inputs can't be parsed into a config, so
        # we should bail out with a 400 before saving anything to the HogFunction.
        source = self._create_stripe_source(job_inputs={})
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_test"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["message"] == "Source has no configuration"
        mock_inputs_updated.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    def test_update_webhook_inputs_rejects_invalid_keys(self, mock_inputs_updated):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"nonexistent_key": "value"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid input keys" in response.json()["message"]
        mock_inputs_updated.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    def test_update_webhook_inputs_no_hog_function(self, mock_inputs_updated):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_test"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No webhook function found" in response.json()["message"]
        mock_inputs_updated.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs_rejects_blanked_required_field(self, mock_create_webhook):
        mock_create_webhook.return_value = self._webhook_result()
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": ""}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "signing_secret" in response.json()["message"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs_partial_update_preserves_other_required_fields(self, mock_create_webhook):
        from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        mock_create_webhook.return_value = self._webhook_result(extra_inputs={"signing_secret": "whsec_initial"})
        self._create_hog_function_template()
        source = self._create_stripe_source()
        self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/")

        # Inject a second required webhook field into the source config so we can test
        # that a partial update which omits one required field is accepted while still
        # preserving the existing value on the HogFunction.
        from products.warehouse_sources.backend.facade.types import ExternalDataSourceType
        from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry

        original_source = SourceRegistry.get_source(ExternalDataSourceType("Stripe"))
        original_config = original_source.get_source_config
        extra_field = SourceFieldInputConfig(
            name="extra_required",
            label="Extra required",
            type=SourceFieldInputConfigType.TEXT,
            required=True,
            placeholder="",
            secret=False,
        )
        patched_config = original_config.model_copy(
            update={"webhookFields": [*(original_config.webhookFields or []), extra_field]}
        )

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_source_config",
            new_callable=PropertyMock,
            return_value=patched_config,
        ):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
                data={"inputs": {"signing_secret": "whsec_rotated"}},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["success"] is True

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        assert hog_function.encrypted_inputs is not None
        assert hog_function.encrypted_inputs["signing_secret"]["value"] == "whsec_rotated"

    def test_update_webhook_inputs_rejects_non_webhook_source(self):
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
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_test"}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "does not support webhooks" in response.json()["message"]

    def test_update_webhook_inputs_rejects_empty_payload(self):
        source = self._create_stripe_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No inputs provided" in response.json()["message"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.webhook_inputs_updated"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_update_webhook_inputs_rotates_secret_without_webhook_schemas(
        self, mock_create_webhook, mock_inputs_updated
    ):
        # Regression for Zendesk 57818: the signing secret is a source-level credential
        # stored on the HogFunction inputs, not per-schema. A source can legitimately
        # have zero schemas on webhook sync (e.g. Stripe with all schemas on incremental
        # polling) and still need its signing secret rotated to keep the existing
        # webhook hog function authenticating deliveries.
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        mock_create_webhook.return_value = self._webhook_result()
        mock_inputs_updated.return_value = (True, None)

        self._create_hog_function_template()
        source = self._create_stripe_source()
        schema = self._create_webhook_schema(source, STRIPE_CUSTOMER_RESOURCE_NAME)
        self.client.post(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/create_webhook/")

        schema.sync_type = ExternalDataSchema.SyncType.INCREMENTAL
        schema.save(update_fields=["sync_type"])

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_webhook_inputs/",
            data={"inputs": {"signing_secret": "whsec_rotated"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["success"] is True

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook")
        assert hog_function.encrypted_inputs is not None
        assert hog_function.encrypted_inputs["signing_secret"]["value"] == "whsec_rotated"
        mock_inputs_updated.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    def test_create_webhook_maps_all_webhook_schemas(self, mock_create_webhook):
        """Regression: creating a source with multiple webhook tables then hitting the
        create_webhook endpoint must populate schema_mapping for every webhook schema.
        Webhook schemas have sync_type='webhook' (not 'incremental')."""
        mock_create_webhook.return_value = self._webhook_result()
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.constants import (
            RESOURCE_TO_STRIPE_OBJECT_TYPE,
        )

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
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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

    def test_webhook_info_non_webhook_source(self):
        source = self._create_postgres_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["supports_webhooks"] is False

    def test_webhook_info_no_hog_function(self):
        source = self._create_stripe_source()

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["supports_webhooks"] is True
        assert data["exists"] is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_with_hog_function(self, mock_get_info):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

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

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_desired_webhook_events"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_reports_missing_events(self, mock_get_info, mock_desired):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(
            exists=True,
            status="enabled",
            enabled_events=["charge.created"],
        )
        mock_desired.return_value = ["charge.created", "customer.created", "customer.updated"]

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["missing_events"] == ["customer.created", "customer.updated"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_desired_webhook_events"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_no_missing_events_when_in_sync(self, mock_get_info, mock_desired):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(
            exists=True,
            status="enabled",
            enabled_events=["charge.created", "customer.created"],
        )
        mock_desired.return_value = ["charge.created", "customer.created"]

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["missing_events"] == []

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_desired_webhook_events"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_wildcard_endpoint_has_no_missing_events(self, mock_get_info, mock_desired):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(exists=True, status="enabled", enabled_events=["*"])
        mock_desired.return_value = ["charge.created", "customer.created"]

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["missing_events"] == []

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_external_not_found(self, mock_get_info):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

        mock_get_info.return_value = ExternalWebhookInfo(exists=False)

        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["exists"] is True
        assert data["external_status"]["exists"] is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info"
    )
    def test_webhook_info_external_error(self, mock_get_info):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ExternalWebhookInfo

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

    def test_webhook_info_source_returns_none(self):
        """When a source doesn't implement get_external_webhook_info, external_status should be null."""
        source = self._create_stripe_source()
        self._create_hog_function(source)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info",
            return_value=None,
        ):
            response = self.client.get(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/"
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["exists"] is True
        assert data["external_status"] is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info",
        return_value=None,
    )
    def test_webhook_info_masks_set_secret_input(self, _mock_info):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        source = self._create_stripe_source()
        hog_function = self._create_hog_function(source)
        hog_function.inputs_schema = [
            *hog_function.inputs_schema,
            {"type": "string", "key": "signing_secret", "label": "Signing secret", "required": True, "secret": True},
        ]
        hog_function.encrypted_inputs = {"signing_secret": {"value": "whsec_existing"}}
        hog_function.save()
        # Sanity check the model routed the secret correctly.
        hog_function.refresh_from_db()
        assert (
            HogFunction.objects.get(pk=hog_function.pk).encrypted_inputs["signing_secret"]["value"] == "whsec_existing"
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["inputs"] == {"signing_secret": {"secret": True}}

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.get_external_webhook_info",
        return_value=None,
    )
    def test_webhook_info_omits_unset_inputs(self, _mock_info):
        source = self._create_stripe_source()
        self._create_hog_function(source)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/webhook_info/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["inputs"] == {}


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
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_delete_webhook_success(self, mock_delete_webhook):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookDeletionResult

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

    def test_delete_webhook_blocked_by_webhook_schemas(self):
        source = self._create_stripe_source()
        self._create_webhook_schema(source, "Customers")
        self._create_hog_function(source)

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "webhook sync" in response.json()["message"]
        assert "Customers" in response.json()["message"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_delete_webhook_external_fails_still_deletes_hog_function(self, mock_delete_webhook):
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookDeletionResult

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

    def test_delete_webhook_no_hog_function(self):
        source = self._create_stripe_source()

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/delete_webhook/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert data["external_deleted"] is False

    def test_delete_webhook_non_webhook_source(self):
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

    def test_delete_webhook_no_job_inputs_still_cleans_up_hog_function(self):
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
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook")
    def test_destroy_source_deletes_webhook_and_hog_function(self, mock_delete_webhook):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import WebhookDeletionResult

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

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.delete_webhook",
        side_effect=Exception("Stripe API error"),
    )
    def test_destroy_source_continues_if_webhook_cleanup_fails(self, _mock_delete_webhook, mock_capture_exception):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

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


def _make_postgres_source(
    team_id: int,
    user,
    *,
    cdc_enabled: bool = False,
    management_mode: str = "posthog",
    slot_name: str = "posthog_slot",
    pub_name: str = "posthog_pub",
    extra_job_inputs: dict | None = None,
    source_type: str = "Postgres",
) -> ExternalDataSource:
    job_inputs: dict[str, t.Any] = {
        "host": "localhost",
        "port": 5432,
        "database": "app",
        "user": "user",
        "password": "pass",
        "schema": "public",
    }
    if cdc_enabled:
        job_inputs.update(
            {
                "cdc_enabled": True,
                "cdc_management_mode": management_mode,
                "cdc_slot_name": slot_name,
                "cdc_publication_name": pub_name,
                "cdc_auto_drop_slot": True,
                "cdc_lag_warning_threshold_mb": 512,
                "cdc_lag_critical_threshold_mb": 2048,
                "cdc_consistent_point": "0/12345",
            }
        )
    if extra_job_inputs:
        job_inputs.update(extra_job_inputs)
    return ExternalDataSource.objects.create(
        team_id=team_id,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        source_type=source_type,
        created_by=user,
        prefix="pg_",
        job_inputs=job_inputs,
    )


class TestCheckCDCPrerequisitesForSource(APIBaseTest):
    def test_rejects_source_type_without_cdc_support(self) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        assert "CDC is not supported" in response.json()["message"]

    def test_rejects_invalid_management_mode(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "nonsense"},
            format="json",
        )
        assert response.status_code == 400
        assert "cdc_management_mode" in response.json()["message"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    def test_uses_stored_credentials_not_client_payload(self, mock_validate) -> None:
        # The whole point of this endpoint: the client never sends the password (it's
        # stripped from API responses), so prereqs must validate against the stored source.
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.json() == {"valid": True, "errors": []}
        # The adapter was handed the stored source model — not a client-supplied config dict.
        called_source = mock_validate.call_args.args[0]
        assert called_source.pk == source.pk

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=["wal_level must be 'logical'"],
    )
    def test_returns_errors_when_prereqs_fail(self, _mock_validate) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["valid"] is False
        assert body["errors"] == ["wal_level must be 'logical'"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    def test_forwards_self_managed_publication_name(self, mock_validate) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "self_managed", "cdc_publication_name": "customer_pub"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert mock_validate.call_args.kwargs["publication_name"] == "customer_pub"
        assert mock_validate.call_args.kwargs["management_mode"] == "self_managed"

    @parameterized.expand(
        [
            (
                "ssl_required_error",
                SSLRequiredError("SSL/TLS connection is required but your database does not support it."),
            ),
            (
                "operational_error",
                psycopg.OperationalError(
                    'connection failed: connection to server at "127.0.0.1", port 5434 failed: '
                    "server does not support SSL, but SSL was required"
                ),
            ),
            ("ssh_tunnel_error", BaseSSHTunnelForwarderError("Could not establish session to SSH gateway")),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    def test_connection_failure_returns_400_without_capture(self, _name, exc, mock_capture) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        with patch.object(PostgresCDCAdapter, "validate_prerequisites", side_effect=exc):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
                data={"cdc_management_mode": "posthog"},
                format="json",
            )
        assert response.status_code == 400
        assert "Could not connect to source" in response.json()["message"]
        # User/upstream connection failures must not pollute error tracking.
        mock_capture.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch.object(PostgresCDCAdapter, "validate_prerequisites", side_effect=ValueError("unexpected bug"))
    def test_unexpected_error_is_still_captured(self, _mock_validate, mock_capture) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/check_cdc_prerequisites_for_source/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        mock_capture.assert_called_once()


class TestCheckCDCPrerequisitesWizard(APIBaseTest):
    """The detail=False wizard endpoint validates a client-supplied Postgres config before the
    source exists. Connecting to a user's database is expected to fail on bad creds/host/tunnel,
    so those connection errors should surface as a 400 without being captured to error tracking."""

    BASE_PAYLOAD = {
        "source_type": "Postgres",
        "host": "db.example.com",
        "port": 5432,
        "database": "postgres",
        "user": "postgres",
        "password": "password",
        "cdc_management_mode": "posthog",
        "tables": ["public.users"],
    }

    def _post(self, **overrides):
        return self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/check_cdc_prerequisites/",
            data={**self.BASE_PAYLOAD, **overrides},
            format="json",
        )

    @parameterized.expand(
        [
            (
                "operational_error",
                psycopg.OperationalError(
                    'connection failed: connection to server at "127.0.0.1", port 46377 failed: '
                    "server closed the connection unexpectedly"
                ),
            ),
            ("ssh_tunnel_error", BaseSSHTunnelForwarderError("Could not establish session to SSH gateway")),
            ("ssl_required_error", SSLRequiredError("SSL/TLS is required but not supported by the server")),
        ]
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch.object(PostgresSource, "is_database_host_valid", return_value=(True, None))
    @patch.object(PostgresSource, "ssh_tunnel_is_valid", return_value=(True, None))
    def test_connection_failure_returns_400_without_capture(
        self, _name, exc, _mock_ssh, _mock_host, mock_capture
    ) -> None:
        with patch.object(PostgresSource, "check_cdc_prerequisites", side_effect=exc):
            response = self._post()
        assert response.status_code == 400, response.content
        assert "Could not connect to Postgres to check prerequisites" in response.json()["message"]
        # User/upstream connection failures must not pollute error tracking.
        mock_capture.assert_not_called()

    @patch.object(PostgresSource, "is_database_host_valid", return_value=(True, None))
    @patch.object(PostgresSource, "ssh_tunnel_is_valid", return_value=(True, None))
    @patch.object(PostgresSource, "check_cdc_prerequisites", return_value=[])
    def test_supabase_source_type_is_accepted(self, _mock_prereqs, _mock_ssh, _mock_host) -> None:
        # Supabase is Postgres on the wire — the prereq endpoint must not reject it by source type.
        response = self._post(source_type="Supabase")
        assert response.status_code == 200, response.content
        assert response.json() == {"valid": True, "errors": []}

    def test_unsupported_source_type_is_rejected(self) -> None:
        response = self._post(source_type="Stripe")
        assert response.status_code == 400
        assert "only supported for" in response.json()["message"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch.object(PostgresSource, "is_database_host_valid", return_value=(True, None))
    @patch.object(PostgresSource, "ssh_tunnel_is_valid", return_value=(True, None))
    @patch.object(PostgresSource, "check_cdc_prerequisites", side_effect=ValueError("unexpected bug"))
    def test_unexpected_error_is_still_captured(self, _mock_prereqs, _mock_ssh, _mock_host, mock_capture) -> None:
        response = self._post()
        assert response.status_code == 400, response.content
        # Genuine bugs (not connection failures) should still be captured.
        mock_capture.assert_called_once()


class TestEnableCDC(APIBaseTest):
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    def test_enable_cdc_rejects_source_type_without_cdc_support(self, _flag) -> None:
        # Stripe has no CDC adapter — the viewset must surface that as a 400, not crash.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        assert "CDC is not supported" in response.json()["message"]

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=False,
    )
    def test_enable_cdc_rejects_when_team_flag_off(self, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 403

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    def test_enable_cdc_rejects_when_already_enabled(self, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 409

    @parameterized.expand(
        [
            ("blank", ""),
            ("invalid", "garbage_mode"),
            ("none", None),
        ]
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    def test_enable_cdc_rejects_invalid_management_mode(self, _name: str, mode_value, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": mode_value},
            format="json",
        )
        assert response.status_code == 400
        assert "cdc_management_mode" in response.json()["message"]

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=["wal_level must be 'logical'", "Missing REPLICATION privilege"],
    )
    def test_enable_cdc_returns_400_when_prereqs_fail(self, _check, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        body = response.json()
        assert body["message"] == "CDC prerequisites not met."
        assert body["errors"] == ["wal_level must be 'logical'", "Missing REPLICATION privilege"]
        source.refresh_from_db()
        assert (source.job_inputs or {}).get("cdc_enabled") is not True

    @parameterized.expand(
        [
            (
                "ssl_required_error",
                SSLRequiredError("SSL/TLS connection is required but your database does not support it."),
            ),
            (
                "operational_error",
                psycopg.OperationalError(
                    'connection failed: connection to server at "127.0.0.1", port 5434 failed: '
                    "server does not support SSL, but SSL was required"
                ),
            ),
            ("ssh_tunnel_error", BaseSSHTunnelForwarderError("Could not establish session to SSH gateway")),
        ]
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    def test_enable_cdc_connection_failure_returns_400_without_capture(self, _name, exc, mock_capture, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        with patch.object(PostgresCDCAdapter, "validate_prerequisites", side_effect=exc):
            response = self.client.post(
                f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
                data={"cdc_management_mode": "posthog"},
                format="json",
            )
        assert response.status_code == 400
        assert "Could not connect to source" in response.json()["message"]
        # User/upstream connection failures must not pollute error tracking.
        mock_capture.assert_not_called()

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    @patch.object(PostgresCDCAdapter, "validate_prerequisites", side_effect=ValueError("unexpected bug"))
    def test_enable_cdc_unexpected_error_is_still_captured(self, _check, mock_capture, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        mock_capture.assert_called_once()

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_cdc_slot_cleanup_schedule")
    def test_enable_cdc_posthog_managed_success(
        self,
        mock_ensure_cleanup,
        mock_sync_extraction,
        mock_setup_cdc_resources,
        _check,
        _flag,
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user)

        def setup_cdc_slot(_adapter, source_model, payload):
            job_inputs = dict(source_model.job_inputs or {})
            job_inputs.update(
                {
                    "cdc_enabled": True,
                    "cdc_management_mode": payload.get("cdc_management_mode", "posthog"),
                    "cdc_slot_name": payload.get("cdc_slot_name") or f"posthog_{source_model.id.hex[:12]}",
                    "cdc_publication_name": (
                        payload.get("cdc_publication_name") or f"posthog_pub_{source_model.id.hex[:12]}"
                    ),
                    "cdc_auto_drop_slot": payload.get("cdc_auto_drop_slot", True),
                    "cdc_lag_warning_threshold_mb": payload.get("cdc_lag_warning_threshold_mb", 512),
                    "cdc_lag_critical_threshold_mb": payload.get("cdc_lag_critical_threshold_mb", 2048),
                    "cdc_consistent_point": "0/ABCDEF",
                }
            )
            source_model.job_inputs = job_inputs
            source_model.save(update_fields=["job_inputs", "updated_at"])
            return None

        mock_setup_cdc_resources.side_effect = setup_cdc_slot

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={
                "cdc_management_mode": "posthog",
                "cdc_auto_drop_slot": False,
                "cdc_lag_warning_threshold_mb": 512,
                "cdc_lag_critical_threshold_mb": 4096,
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json() == {"success": True, "schedules_ready": True}

        source.refresh_from_db()
        ji = source.job_inputs or {}
        # `EncryptedJSONField` round-trips scalar values as strings.
        assert ji["cdc_enabled"] == "True"
        assert ji["cdc_management_mode"] == "posthog"
        assert ji["cdc_auto_drop_slot"] == "False"
        assert int(ji["cdc_lag_warning_threshold_mb"]) == 512
        assert int(ji["cdc_lag_critical_threshold_mb"]) == 4096
        assert ji["cdc_consistent_point"] == "0/ABCDEF"

        mock_sync_extraction.assert_called_once()
        mock_ensure_cleanup.assert_called_once()

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_cdc_slot_cleanup_schedule")
    def test_enable_cdc_succeeds_for_supabase(
        self,
        _mock_ensure_cleanup,
        _mock_sync_extraction,
        mock_setup_cdc_resources,
        _check,
        _flag,
    ) -> None:
        # Supabase reuses the Postgres CDC adapter, so the source-type gate must let it through.
        source = _make_postgres_source(self.team.pk, self.user, source_type="Supabase")
        mock_setup_cdc_resources.return_value = None

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )

        assert response.status_code == 200, response.content

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_cdc_slot_cleanup_schedule")
    def test_enable_cdc_self_managed_passes_publication_name(
        self,
        _mock_ensure_cleanup,
        _mock_sync_extraction,
        mock_setup_cdc_resources,
        mock_check,
        _flag,
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user)

        def setup_cdc_slot(_adapter, source_model, payload):
            job_inputs = dict(source_model.job_inputs or {})
            job_inputs.update(
                {
                    "cdc_enabled": True,
                    "cdc_management_mode": "self_managed",
                    "cdc_slot_name": f"posthog_{source_model.id.hex[:12]}",
                    "cdc_publication_name": payload.get("cdc_publication_name") or "posthog_pub",
                    "cdc_consistent_point": "0/DEADBEEF",
                }
            )
            source_model.job_inputs = job_inputs
            source_model.save(update_fields=["job_inputs", "updated_at"])
            return None

        mock_setup_cdc_resources.side_effect = setup_cdc_slot

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={
                "cdc_management_mode": "self_managed",
                "cdc_publication_name": "customer_pub",
            },
            format="json",
        )

        assert response.status_code == 200, response.content
        # Prereq check forwarded the publication name we received.
        assert mock_check.call_args.kwargs["publication_name"] == "customer_pub"

        source.refresh_from_db()
        ji = source.job_inputs or {}
        assert ji["cdc_management_mode"] == "self_managed"
        assert ji["cdc_publication_name"] == "customer_pub"

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.ExternalDataSourceViewSet._setup_cdc_resources"
    )
    def test_enable_cdc_returns_400_when_slot_setup_fails(self, mock_setup_cdc_resources, _check, _flag) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        mock_setup_cdc_resources.return_value = "Failed to create replication slot: connection lost"

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={"cdc_management_mode": "posthog"},
            format="json",
        )
        assert response.status_code == 400
        assert "connection lost" in response.json()["message"]

        # Source must NOT be deleted (this is not the create path).
        source.refresh_from_db()
        assert source.deleted is False
        assert (source.job_inputs or {}).get("cdc_enabled") is not True

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.publication_exists",
        return_value=False,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.slot_exists",
        return_value=False,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.drop_slot_and_publication"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.drop_slot")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.drop_publication")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.create_slot")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.create_publication")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.cdc_pg_connection")
    def test_enable_cdc_posthog_rolls_back_partial_slot_on_failure(
        self,
        mock_cdc_pg_connection,
        mock_create_publication,
        mock_create_slot,
        mock_drop_publication,
        mock_drop_slot,
        mock_drop_slot_and_publication,
        _mock_slot_exists,
        _mock_publication_exists,
        _check,
        _flag,
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user)

        # Fake a no-op connection context — actual slot calls are themselves mocked.
        mock_cdc_pg_connection.return_value.__enter__.return_value = object()
        mock_cdc_pg_connection.return_value.__exit__.return_value = None

        # Publication is created first; the slot creation then fails (e.g. max_replication_slots reached).
        mock_create_slot.side_effect = RuntimeError("max_replication_slots reached")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={
                "cdc_management_mode": "posthog",
                "cdc_slot_name": "leaky_slot",
                "cdc_publication_name": "leaky_pub",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "max_replication_slots reached" in response.json()["message"]

        # Only the publication was created before the slot failed, so rollback drops just the publication.
        mock_create_publication.assert_called_once()
        mock_drop_publication.assert_called_once()
        assert mock_drop_publication.call_args.args[1] == "leaky_pub"
        mock_drop_slot.assert_not_called()
        mock_drop_slot_and_publication.assert_not_called()

        # Source's job_inputs must NOT have been persisted with cdc_enabled — we never reached save().
        source.refresh_from_db()
        assert (source.job_inputs or {}).get("cdc_enabled") is not True
        assert source.deleted is False

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.is_cdc_enabled_for_team",
        return_value=True,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.validate_prerequisites",
        return_value=[],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.drop_slot_and_publication"
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.drop_slot")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.create_slot")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.slot_exists",
        return_value=False,
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.publication_exists",
        return_value=True,
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.cdc_pg_connection")
    def test_enable_cdc_self_managed_rolls_back_slot_only_on_failure(
        self,
        mock_cdc_pg_connection,
        _mock_publication_exists,
        _mock_slot_exists,
        mock_create_slot,
        mock_drop_slot,
        mock_drop_slot_and_publication,
        _check,
        _flag,
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user)

        mock_cdc_pg_connection.return_value.__enter__.return_value = object()
        mock_cdc_pg_connection.return_value.__exit__.return_value = None

        mock_create_slot.side_effect = RuntimeError("replication permission denied")

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/enable_cdc/",
            data={
                "cdc_management_mode": "self_managed",
                "cdc_slot_name": "self_slot",
                "cdc_publication_name": "customer_owned_pub",
            },
            format="json",
        )

        assert response.status_code == 400
        assert "replication permission denied" in response.json()["message"]

        # In self-managed mode the publication is customer-owned — only drop the slot.
        mock_drop_slot.assert_called_once()
        assert mock_drop_slot.call_args.args[1] == "self_slot"
        mock_drop_slot_and_publication.assert_not_called()

        source.refresh_from_db()
        assert (source.job_inputs or {}).get("cdc_enabled") is not True
        assert source.deleted is False


class TestDisableCDC(APIBaseTest):
    def test_disable_cdc_rejects_source_type_without_cdc_support(self) -> None:
        # Stripe has no CDC adapter — the viewset must surface that as a 400, not crash.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 400
        assert "CDC is not supported" in response.json()["message"]

    def test_disable_cdc_noops_when_cdc_not_enabled(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body.get("already_disabled") is True

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    def test_disable_cdc_clears_cdc_keys_and_pauses_schemas(self, _cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)

        cdc_schema = ExternalDataSchema.objects.create(
            name="cdc_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        )
        non_cdc_schema = ExternalDataSchema.objects.create(
            name="incremental_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            should_sync=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content

        source.refresh_from_db()
        ji = source.job_inputs or {}
        # Every cdc_* key must be gone — leaving a stale consistent_point behind
        # would corrupt LSN tracking on re-enable.
        assert not any(k.startswith("cdc_") for k in ji.keys())
        # Non-CDC connection fields are preserved.
        assert ji["host"] == "localhost"
        assert ji["user"] == "user"

        cdc_schema.refresh_from_db()
        assert cdc_schema.sync_type is None
        assert cdc_schema.should_sync is False

        # Non-CDC schema must NOT be touched.
        non_cdc_schema.refresh_from_db()
        assert non_cdc_schema.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
        assert non_cdc_schema.should_sync is True

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    def test_disable_cdc_soft_deletes_companion_cdc_tables(self, _cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)

        cdc_companion = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="pg_orders_cdc",
            external_data_source_id=source.pk,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="s3://bucket/orders_cdc",
        )
        main_table = DataWarehouseTable.objects.create(
            team_id=self.team.pk,
            name="pg_orders",
            external_data_source_id=source.pk,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="s3://bucket/orders",
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content

        cdc_companion.refresh_from_db()
        assert cdc_companion.deleted is True

        # Non-_cdc-suffixed table must NOT be soft-deleted by disable_cdc —
        # the user might still pick a new sync strategy and reuse it.
        main_table.refresh_from_db()
        assert main_table.deleted is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cancel_external_data_workflow")
    def test_disable_cdc_cancels_running_workflow(self, mock_cancel, _cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        cdc_schema = ExternalDataSchema.objects.create(
            name="cdc_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        )
        running_job = ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            team_id=self.team.pk,
            schema=cdc_schema,
            workflow_id="cdc-extraction-running-workflow",
            status="Running",
            rows_synced=0,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content
        mock_cancel.assert_called_once_with(running_job.workflow_id)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cancel_external_data_workflow")
    def test_disable_cdc_does_not_cancel_non_cdc_running_jobs(self, mock_cancel, _cleanup) -> None:
        # A running incremental sync on the same source must NOT be cancelled by disable_cdc.
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        incremental_schema = ExternalDataSchema.objects.create(
            name="incremental_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            should_sync=True,
        )
        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            team_id=self.team.pk,
            schema=incremental_schema,
            workflow_id="incremental-running-workflow",
            status="Running",
            rows_synced=0,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content
        mock_cancel.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.cancel_external_data_workflow")
    def test_disable_cdc_does_not_cancel_non_running_workflow(self, mock_cancel, _cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        ExternalDataJob.objects.create(
            pipeline_id=source.pk,
            team_id=self.team.pk,
            workflow_id="cdc-extraction-completed-workflow",
            status="Completed",
            rows_synced=10,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content
        mock_cancel.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        side_effect=RuntimeError("slot drop network blip"),
    )
    def test_disable_cdc_succeeds_even_if_external_cleanup_fails(self, _cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        cdc_schema = ExternalDataSchema.objects.create(
            name="cdc_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        )

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        # The user's intent to disable CDC must be honored even if the customer's DB
        # is briefly unreachable for the slot drop — we still clear local state.
        assert response.status_code == 200, response.content

        source.refresh_from_db()
        ji = source.job_inputs or {}
        assert "cdc_enabled" not in ji

        cdc_schema.refresh_from_db()
        assert cdc_schema.sync_type is None
        assert cdc_schema.should_sync is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.cleanup_resources",
        return_value=None,
    )
    def test_disable_cdc_calls_source_cleanup_helper(self, mock_cleanup) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/disable_cdc/",
        )
        assert response.status_code == 200, response.content

        # Helper called with the source model (drops schedule + slot + publication).
        mock_cleanup.assert_called_once()
        called_with = mock_cleanup.call_args.args[0]
        assert called_with.pk == source.pk


BROKEN_MARKER = {"reason": "slot_missing", "at": "2026-06-29T10:40:00+00:00"}


class TestRepairCDC(APIBaseTest):
    def _repair(self, source: ExternalDataSource):
        return self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/repair_cdc/",
        )

    def test_repair_cdc_rejects_when_cdc_not_enabled(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self._repair(source)
        assert response.status_code == 400
        assert "CDC is not enabled" in response.json()["message"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot"
    )
    def test_repair_cdc_rejects_when_no_active_cdc_schemas(self, mock_recreate) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        ExternalDataSchema.objects.create(
            name="incremental_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            should_sync=True,
        )
        response = self._repair(source)
        assert response.status_code == 400
        assert "no active CDC schemas" in response.json()["message"]
        mock_recreate.assert_not_called()

    @patch("products.data_warehouse.backend.logic.data_load.service.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.trigger_external_data_workflow")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_external_data_schedule")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot",
        return_value={"cdc_consistent_point": "0/AABBCC"},
    )
    def test_repair_cdc_resets_schemas_and_resumes_schedules(
        self, mock_recreate, mock_unpause_schema, mock_trigger, mock_unpause_extraction, mock_sync_extraction
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        source.status = ExternalDataSource.Status.ERROR
        source.save()

        broken_schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            status=ExternalDataSchema.Status.FAILED,
            latest_error="The replication slot no longer exists on the source database.",
            initial_sync_complete=True,
            sync_type_config={
                "cdc_mode": "streaming",
                "cdc_last_log_position": "0/123",
                "cdc_deferred_runs": [{"run": "stale"}],
                "cdc_broken": BROKEN_MARKER,
            },
        )
        streaming_schema = ExternalDataSchema.objects.create(
            name="users",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            initial_sync_complete=True,
            sync_type_config={"cdc_mode": "streaming", "cdc_broken": BROKEN_MARKER},
        )
        disabled_cdc_schema = ExternalDataSchema.objects.create(
            name="ignored",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=False,
            sync_type_config={"cdc_mode": "streaming"},
        )
        non_cdc_schema = ExternalDataSchema.objects.create(
            name="incremental_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            should_sync=True,
        )

        response = self._repair(source)
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["success"] is True
        assert body["schemas_reset"] == 2

        # Slot recreated against the qualified capture set of active CDC schemas only.
        mock_recreate.assert_called_once()
        assert sorted(mock_recreate.call_args.kwargs["tables"]) == ["public.orders", "public.users"]

        for schema in (broken_schema, streaming_schema):
            schema.refresh_from_db()
            config = schema.sync_type_config
            assert config["cdc_mode"] == "snapshot"
            assert config["reset_pipeline"] is True
            assert "cdc_broken" not in config
            assert "cdc_last_log_position" not in config
            assert "cdc_deferred_runs" not in config
            assert schema.initial_sync_complete is False
            assert schema.latest_error is None

        disabled_cdc_schema.refresh_from_db()
        assert disabled_cdc_schema.sync_type_config == {"cdc_mode": "streaming"}
        non_cdc_schema.refresh_from_db()
        assert non_cdc_schema.sync_type_config == {}

        source.refresh_from_db()
        assert source.job_inputs["cdc_consistent_point"] == "0/AABBCC"
        assert source.status == ExternalDataSource.Status.RUNNING

        unpaused_ids = {call.args[0] for call in mock_unpause_schema.call_args_list}
        assert unpaused_ids == {str(broken_schema.id), str(streaming_schema.id)}
        triggered_ids = {str(call.args[0].id) for call in mock_trigger.call_args_list}
        assert triggered_ids == {str(broken_schema.id), str(streaming_schema.id)}
        mock_sync_extraction.assert_called_once()
        mock_unpause_extraction.assert_called_once_with(str(source.pk))

    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.trigger_external_data_workflow")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_external_data_schedule")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot",
        side_effect=psycopg.OperationalError("connection refused"),
    )
    def test_repair_cdc_failure_keeps_broken_state(
        self, _mock_recreate, mock_unpause_schema, mock_trigger, mock_unpause_extraction
    ) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            status=ExternalDataSchema.Status.FAILED,
            sync_type_config={"cdc_mode": "streaming", "cdc_broken": BROKEN_MARKER},
        )

        response = self._repair(source)
        assert response.status_code == 400
        assert "Could not connect to source to repair CDC" in response.json()["message"]

        # Broken state must survive a failed repair so a retry starts from the same place.
        schema.refresh_from_db()
        assert schema.sync_type_config["cdc_broken"] == BROKEN_MARKER
        assert schema.status == ExternalDataSchema.Status.FAILED
        mock_unpause_schema.assert_not_called()
        mock_trigger.assert_not_called()
        mock_unpause_extraction.assert_not_called()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.get_status"
    )
    def test_repair_cdc_rejects_healthy_source(self, mock_status, mock_recreate) -> None:
        # No broken markers and a live probe showing slot + publication present: repair must
        # refuse — otherwise a stray API call drops a healthy slot and forces a full re-sync.
        mock_status.return_value = {"slot_exists": True, "publication_exists": True, "lag_bytes": 0}
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            sync_type_config={"cdc_mode": "streaming"},
        )

        response = self._repair(source)
        assert response.status_code == 400
        assert "CDC looks healthy" in response.json()["message"]
        mock_recreate.assert_not_called()

    @patch("products.data_warehouse.backend.logic.data_load.service.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.trigger_external_data_workflow")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_external_data_schedule")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot",
        return_value={"cdc_consistent_point": "0/AABBCC"},
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.get_status",
        return_value={"slot_exists": False, "publication_exists": True, "lag_bytes": None},
    )
    def test_repair_cdc_allows_missing_slot_without_marker(
        self, mock_status, mock_recreate, _unpause, _trigger, _unpause_ext, _sync_ext
    ) -> None:
        # A slot dropped on the source database before any extraction run noticed leaves no
        # cdc_broken marker — the live probe is the evidence that lets repair proceed.
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            sync_type_config={"cdc_mode": "streaming"},
        )

        response = self._repair(source)
        assert response.status_code == 200, response.content
        mock_recreate.assert_called_once()

    @patch("products.data_warehouse.backend.logic.data_load.service.cancel_external_data_workflow")
    @patch("products.data_warehouse.backend.logic.data_load.service.sync_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_cdc_extraction_schedule")
    @patch("products.data_warehouse.backend.logic.data_load.service.trigger_external_data_workflow")
    @patch("products.data_warehouse.backend.logic.data_load.service.unpause_external_data_schedule")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.recreate_slot",
        return_value={"cdc_consistent_point": "0/AABBCC"},
    )
    def test_repair_cdc_cancels_running_cdc_jobs(
        self, _mock_recreate, _unpause, _trigger, _unpause_ext, _sync_ext, mock_cancel
    ) -> None:
        # A run still holding the slot fails pg_drop_replication_slot, and a wedged Running
        # workflow would block the resumed SKIP-overlap schedules — repair must cancel them.
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        cdc_schema = ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            sync_type_config={"cdc_mode": "streaming", "cdc_broken": BROKEN_MARKER},
        )
        non_cdc_schema = ExternalDataSchema.objects.create(
            name="incremental_table",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
            should_sync=True,
        )
        ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.pk,
            schema_id=cdc_schema.id,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="cdc-workflow-1",
            rows_synced=0,
        )
        ExternalDataJob.objects.create(
            team_id=self.team.pk,
            pipeline_id=source.pk,
            schema_id=non_cdc_schema.id,
            status=ExternalDataJob.Status.RUNNING,
            workflow_id="incremental-workflow-1",
            rows_synced=0,
        )

        response = self._repair(source)
        assert response.status_code == 200, response.content
        # Only the CDC schema's run is cancelled — unrelated incremental syncs keep running.
        mock_cancel.assert_called_once_with("cdc-workflow-1")

    def test_repair_cdc_conflicts_while_another_repair_holds_the_lock(self) -> None:
        from posthog.redis import get_client

        from products.warehouse_sources.backend.temporal.data_imports.cdc.repair import _repair_lock_key

        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        ExternalDataSchema.objects.create(
            name="orders",
            team_id=self.team.pk,
            source_id=source.pk,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
            sync_type_config={"cdc_mode": "streaming", "cdc_broken": BROKEN_MARKER},
        )

        redis = get_client()
        lock_key = _repair_lock_key(str(source.pk))
        assert redis.set(lock_key, "1", nx=True, ex=60)
        try:
            response = self._repair(source)
        finally:
            redis.delete(lock_key)

        assert response.status_code == 409
        assert "already running" in response.json()["message"]


class TestUpdateCDCSettings(APIBaseTest):
    def test_update_cdc_settings_rejects_source_type_without_cdc_support(self) -> None:
        # Stripe has no CDC adapter — the viewset must surface that as a 400, not crash.
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_lag_warning_threshold_mb": 100},
            format="json",
        )
        assert response.status_code == 400
        assert "CDC is not supported" in response.json()["message"]

    def test_update_cdc_settings_rejects_when_cdc_not_enabled(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_lag_warning_threshold_mb": 100},
            format="json",
        )
        assert response.status_code == 400
        assert "CDC is not enabled" in response.json()["message"]

    @parameterized.expand(
        [
            ("non_numeric", "fast"),
            ("negative", -10),
            ("zero", 0),
        ]
    )
    def test_update_cdc_settings_rejects_invalid_thresholds(self, _name: str, value) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_lag_warning_threshold_mb": value},
            format="json",
        )
        assert response.status_code == 400

    def test_update_cdc_settings_rejects_warn_not_less_than_crit(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={
                "cdc_lag_warning_threshold_mb": 5000,
                "cdc_lag_critical_threshold_mb": 5000,
            },
            format="json",
        )
        assert response.status_code == 400
        assert "less than" in response.json()["message"]

    def test_update_cdc_settings_validates_warn_vs_existing_crit(self) -> None:
        # If only `warning` is sent, we must still compare against the persisted critical value.
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_lag_warning_threshold_mb": 99999},
            format="json",
        )
        assert response.status_code == 400
        assert "less than" in response.json()["message"]

    def test_update_cdc_settings_partial_update_preserves_other_fields(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        original_slot = source.job_inputs["cdc_slot_name"]
        original_pub = source.job_inputs["cdc_publication_name"]
        original_mode = source.job_inputs["cdc_management_mode"]

        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_auto_drop_slot": False},
            format="json",
        )
        assert response.status_code == 200, response.content

        source.refresh_from_db()
        ji = source.job_inputs
        # `EncryptedJSONField` round-trips scalar values as strings.
        assert ji["cdc_auto_drop_slot"] == "False"
        # Untouched fields preserved.
        assert ji["cdc_slot_name"] == original_slot
        assert ji["cdc_publication_name"] == original_pub
        assert ji["cdc_management_mode"] == original_mode
        # Thresholds preserved at defaults.
        assert int(ji["cdc_lag_warning_threshold_mb"]) == 512
        assert int(ji["cdc_lag_critical_threshold_mb"]) == 2048

    def test_update_cdc_settings_empty_payload_is_unchanged(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={},
            format="json",
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["success"] is True
        assert body.get("unchanged") is True

    def test_update_cdc_settings_updates_all_tunable_fields(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={
                "cdc_auto_drop_slot": False,
                "cdc_lag_warning_threshold_mb": 256,
                "cdc_lag_critical_threshold_mb": 2048,
            },
            format="json",
        )
        assert response.status_code == 200, response.content

        source.refresh_from_db()
        ji = source.job_inputs
        # `EncryptedJSONField` round-trips scalar values as strings.
        assert ji["cdc_auto_drop_slot"] == "False"
        assert int(ji["cdc_lag_warning_threshold_mb"]) == 256
        assert int(ji["cdc_lag_critical_threshold_mb"]) == 2048

    def test_update_cdc_settings_coerces_bool_truthiness(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/update_cdc_settings/",
            data={"cdc_auto_drop_slot": True},
            format="json",
        )
        assert response.status_code == 200, response.content

        source.refresh_from_db()
        # `EncryptedJSONField` round-trips scalar values as strings.
        assert source.job_inputs["cdc_auto_drop_slot"] == "True"


class TestCDCJobInputsExposure(APIBaseTest):
    def test_retrieve_exposes_cdc_fields_but_not_password(self) -> None:
        # cdc_* keys aren't source-config form fields; without the explicit allowlist they'd be
        # stripped from reads as "unknown" and the Configuration page would never see CDC as on.
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/")
        assert response.status_code == 200, response.content

        job_inputs = response.json()["job_inputs"]
        assert job_inputs["cdc_enabled"] == "True"
        assert job_inputs["cdc_management_mode"] == "posthog"
        assert job_inputs["cdc_slot_name"] == "posthog_slot"
        assert job_inputs["cdc_publication_name"] == "posthog_pub"
        assert "cdc_lag_warning_threshold_mb" in job_inputs
        assert "cdc_lag_critical_threshold_mb" in job_inputs
        # Secret connection field must still be stripped.
        assert "password" not in job_inputs

    def test_retrieve_omits_cdc_fields_when_not_enabled(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/")
        assert response.status_code == 200, response.content
        job_inputs = response.json()["job_inputs"]
        assert not any(k.startswith("cdc_") for k in job_inputs)


class TestCDCStatus(APIBaseTest):
    def test_rejects_source_type_without_cdc_support(self) -> None:
        source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            job_inputs={"stripe_secret_key": "sk_test_123"},
        )
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/cdc_status/")
        assert response.status_code == 400
        assert "CDC is not supported" in response.json()["message"]

    def test_returns_disabled_when_cdc_off(self) -> None:
        source = _make_postgres_source(self.team.pk, self.user)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/cdc_status/")
        assert response.status_code == 200, response.content
        assert response.json() == {"enabled": False}

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.get_status",
        return_value={"slot_exists": True, "publication_exists": True, "lag_bytes": 2048},
    )
    def test_returns_live_status_when_enabled(self, mock_get_status) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/cdc_status/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["enabled"] is True
        assert body["management_mode"] == "posthog"
        assert body["slot_name"] == "posthog_slot"
        assert body["publication_name"] == "posthog_pub"
        assert body["slot_exists"] is True
        assert body["publication_exists"] is True
        assert body["lag_bytes"] == 2048
        # Read against the stored source model, not a client payload.
        assert mock_get_status.call_args.args[0].pk == source.pk

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.get_status",
        return_value={"slot_exists": False, "publication_exists": True, "lag_bytes": None},
    )
    def test_surfaces_missing_slot(self, _mock_get_status) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/cdc_status/")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["slot_exists"] is False
        assert body["lag_bytes"] is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter.PostgresCDCAdapter.get_status",
        side_effect=psycopg.OperationalError("connection refused"),
    )
    def test_returns_400_when_source_unreachable(self, _mock_get_status) -> None:
        source = _make_postgres_source(self.team.pk, self.user, cdc_enabled=True)
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/{source.pk}/cdc_status/")
        assert response.status_code == 400
        assert "Could not connect to source" in response.json()["message"]


class TestExternalDataSourceConnectLink(APIBaseTest):
    def _connect_link(self, source_type: str):
        return self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/connect_link?source_type={source_type}"
        )

    @parameterized.expand(
        [
            # OAuth-only sources connect via the same page — the form renders the integration picker.
            ("oauth_only", "Hubspot", "oauth"),
            ("credentials_only", "Postgres", "credentials"),
            # Stripe's OAuth option is nested inside the auth_method select alongside API key —
            # the page form offers both, so the user chooses how to authenticate.
            ("mixed_auth", "Stripe", "credentials"),
        ]
    )
    def test_connect_link_always_points_at_the_connect_page(self, _name, source_type, expected_auth_method):
        response = self._connect_link(source_type)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["auth_method"] == expected_auth_method
        assert f"/project/{self.team.pk}/data-warehouse/connect?kind={source_type}" in data["connect_url"]
        # One discovery path for every source: the page stores a credential, the agent passes its id.
        assert "data-warehouse-stored-credentials-list" in data["instructions"]
        assert "credential_id" in data["instructions"]

    def test_connect_link_missing_source_type(self):
        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/connect_link")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_connect_link_unknown_source_type(self):
        response = self._connect_link("NotARealSource")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestExternalDataSourceSetup(APIBaseTest):
    # Stripe enables revenue analytics, whose post-create view sync builds the HogQL Database — patched
    # out here so the test exercises setup's own logic rather than that unrelated side effect.
    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_creates_source_with_all_tables_and_mcp_created_via(
        self, _mock_validate, _mock_sync_views, _mock_person_join
    ):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={
                "source_type": "Stripe",
                "prefix": "stripe_setup_test",
                "payload": {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        source = ExternalDataSource.objects.get(pk=response.json()["id"])
        assert source.created_via == ExternalDataSource.CreatedVia.MCP
        assert source.prefix == "stripe_setup_test"

        schemas = ExternalDataSchema.objects.filter(source=source)
        # Every discovered Stripe endpoint becomes a schema...
        assert schemas.count() == len(STRIPE_ENDPOINTS)
        # ...and the syncable ones are enabled with a sync type (incremental for Stripe's created-based tables).
        synced = schemas.filter(should_sync=True)
        assert synced.exists()
        assert all(s.sync_type in ("incremental", "append", "full_refresh") for s in synced)

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_persists_direct_query_enabled_false(self, _mock_validate, _mock_sync_views, _mock_person_join):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={
                "source_type": "Stripe",
                "direct_query_enabled": False,
                "payload": {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
            },
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        source = ExternalDataSource.objects.get(pk=response.json()["id"])
        assert source.direct_query_enabled is False

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    def test_setup_rejects_source_without_schema_discovery(self, mock_capture_exception):
        # AmazonS3 doesn't implement get_schemas, so the base raises NotImplementedError.
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "AmazonS3", "prefix": "s3_setup_test", "payload": {}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "does not support one-shot setup" in response.json()["message"]
        mock_capture_exception.assert_not_called()
        assert not ExternalDataSource.objects.filter(team=self.team).exists()

    def _create_stripe_webhook_template(self):
        from products.cdp.backend.models.hog_function_template import HogFunctionTemplate

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
                {"type": "json", "key": "schema_mapping", "label": "Schema mapping", "required": True, "hidden": True},
                {"type": "string", "key": "source_id", "label": "Source ID", "required": True, "hidden": True},
            ],
            type="warehouse_source_webhook",
            status="alpha",
            category=[],
        )

    def _setup_stripe(self):
        return self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={
                "source_type": "Stripe",
                "prefix": "stripe_webhook_test",
                "payload": {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
            },
        )

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook",
        return_value=WebhookCreationResult(success=True, extra_inputs={"signing_secret": "whsec_123"}),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_auto_registers_webhook_and_switches_capable_tables(
        self, _mock_validate, _mock_create_webhook, _mock_sync_views, _mock_person_join
    ):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        self._create_stripe_webhook_template()
        response = self._setup_stripe()
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        data = response.json()
        assert data["webhook"]["success"] is True
        assert "/public/webhooks/dwh/" in data["webhook"]["webhook_url"]
        assert data["webhook"]["error"] is None
        assert data["webhook"]["pending_inputs"] == []

        schemas = ExternalDataSchema.objects.filter(source_id=data["id"])
        # Webhook-only tables (no list API) are unlocked by the registered webhook...
        webhook_only = schemas.get(name=STRIPE_DISCOUNT_RESOURCE_NAME)
        assert webhook_only.should_sync is True
        assert webhook_only.sync_type == ExternalDataSchema.SyncType.WEBHOOK
        # ...and dual-capability tables switch from polling to real-time webhook sync.
        customer = schemas.get(name=STRIPE_CUSTOMER_RESOURCE_NAME)
        assert customer.should_sync is True
        assert customer.sync_type == ExternalDataSchema.SyncType.WEBHOOK

        hog_function = HogFunction.objects.get(team=self.team, type="warehouse_source_webhook", deleted=False)
        assert hog_function.enabled is True
        assert hog_function.inputs is not None
        assert hog_function.inputs["source_id"]["value"] == data["id"]

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook",
        return_value=WebhookCreationResult(success=False, error="This API key lacks webhook permissions"),
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_falls_back_to_polling_when_webhook_registration_fails(
        self, _mock_validate, _mock_create_webhook, _mock_sync_views, _mock_person_join
    ):
        from products.cdp.backend.models.hog_functions.hog_function import HogFunction

        self._create_stripe_webhook_template()
        response = self._setup_stripe()
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        data = response.json()
        assert data["webhook"]["success"] is False
        assert "lacks webhook permissions" in data["webhook"]["error"]

        schemas = ExternalDataSchema.objects.filter(source_id=data["id"])
        # Webhook-only tables have no polling fallback, so they stay disabled...
        webhook_only = schemas.get(name=STRIPE_DISCOUNT_RESOURCE_NAME)
        assert webhook_only.should_sync is False
        # ...while dual-capability tables keep their polling sync defaults.
        customer = schemas.get(name=STRIPE_CUSTOMER_RESOURCE_NAME)
        assert customer.should_sync is True
        assert customer.sync_type in ("incremental", "append", "full_refresh")
        # The orphaned handler is removed so nothing dangles.
        assert not HogFunction.objects.filter(team=self.team, type="warehouse_source_webhook", deleted=False).exists()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.create_webhook")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_keeps_polling_defaults_when_webhook_template_missing(
        self, _mock_validate, mock_create_webhook, _mock_sync_views, _mock_person_join
    ):
        response = self._setup_stripe()
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        data = response.json()
        assert data["webhook"]["success"] is False
        assert "sync_hog_function_templates" in data["webhook"]["error"]
        mock_create_webhook.assert_not_called()

        schemas = ExternalDataSchema.objects.filter(source_id=data["id"])
        assert schemas.get(name=STRIPE_DISCOUNT_RESOURCE_NAME).should_sync is False
        customer = schemas.get(name=STRIPE_CUSTOMER_RESOURCE_NAME)
        assert customer.sync_type in ("incremental", "append", "full_refresh")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(False, "Missing Stripe API key"),
    )
    def test_setup_returns_credential_error(self, _mock_validate):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"auth_method": {"selection": "api_key"}}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Missing Stripe API key" in response.json()["message"]
        assert not ExternalDataSource.objects.exists()

    def _store_stripe_credential(self, team=None, **kwargs) -> PendingSourceCredential:
        team = team or self.team
        return PendingSourceCredential.objects.for_team(team.pk).create(
            team=team,
            source_type="Stripe",
            payload={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_stored"}},
            **kwargs,
        )

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.ensure_person_join")
    @patch("products.data_modeling.backend.models.datawarehouse_managed_viewset.DataWarehouseManagedViewSet.sync_views")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_with_credential_id_merges_stored_payload(self, mock_validate, _mock_sync_views, _mock_person_join):
        credential = self._store_stripe_credential()
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"credential_id": str(credential.pk)}},
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        source = ExternalDataSource.objects.get(pk=response.json()["id"])
        assert source.created_via == ExternalDataSource.CreatedVia.MCP
        # The stored secret was merged in server-side and used for validation.
        validated_config = mock_validate.call_args.args[0]
        assert validated_config.auth_method.stripe_secret_key == "sk_test_stored"
        # Stored credentials are single-use — consumed on successful setup.
        assert not PendingSourceCredential.objects.for_team(self.team.pk).exists()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(False, "Invalid Stripe API key"),
    )
    def test_setup_failure_keeps_stored_credential(self, _mock_validate):
        credential = self._store_stripe_credential()
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"credential_id": str(credential.pk)}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert PendingSourceCredential.objects.for_team(self.team.pk).filter(pk=credential.pk).exists()

    @parameterized.expand(
        [
            ("missing", "ba07775f-8eaf-4d09-aa6f-50e37f17f243"),
            ("not_a_uuid", "abc"),
            ("not_a_string", 999999),
        ]
    )
    def test_setup_with_unknown_credential_id_returns_400(self, _name, credential_id):
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"credential_id": credential_id}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not found" in response.json()["message"]
        assert not ExternalDataSource.objects.exists()

    def test_setup_with_expired_credential_returns_400(self):
        credential = self._store_stripe_credential(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"credential_id": str(credential.pk)}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not found or expired" in response.json()["message"]
        assert not ExternalDataSource.objects.exists()

    def test_setup_with_other_teams_credential_returns_400(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        credential = self._store_stripe_credential(team=other_team)
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Stripe", "payload": {"credential_id": str(credential.pk)}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not found" in response.json()["message"]

    def test_setup_with_credential_for_other_source_type_returns_400(self):
        credential = self._store_stripe_credential()
        response = self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/setup/",
            data={"source_type": "Postgres", "payload": {"credential_id": str(credential.pk)}},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "is for 'Stripe'" in response.json()["message"]


class TestExternalDataSourceStoreCredentials(APIBaseTest):
    def _store(self, source_type: str = "Stripe", payload: dict | None = None):
        return self.client.post(
            f"/api/environments/{self.team.pk}/external_data_sources/store_credentials/",
            data={
                "source_type": source_type,
                "payload": payload
                if payload is not None
                else {"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
            },
        )

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_store_credentials_creates_pending_credential_without_source(self, _mock_validate):
        response = self._store()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        data = response.json()
        assert data["source_type"] == "Stripe"

        credential = PendingSourceCredential.objects.for_team(self.team.pk).get(pk=data["credential_id"])
        assert credential.team_id == self.team.pk
        assert credential.source_type == "Stripe"
        assert credential.payload["auth_method"]["stripe_secret_key"] == "sk_test_123"
        assert credential.created_by == self.user
        assert credential.expires_at > timezone.now()
        # Storing credentials must not create a source.
        assert not ExternalDataSource.objects.exists()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_store_credentials_purges_expired_credentials(self, _mock_validate):
        expired = PendingSourceCredential.objects.for_team(self.team.pk).create(
            team=self.team,
            source_type="Stripe",
            payload={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_old"}},
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        response = self._store()
        assert response.status_code == status.HTTP_201_CREATED
        assert not PendingSourceCredential.objects.for_team(self.team.pk).filter(pk=expired.pk).exists()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(False, "Invalid Stripe API key"),
    )
    def test_store_credentials_rejects_invalid_credentials(self, _mock_validate):
        response = self._store()
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid Stripe API key" in response.json()["message"]
        assert not PendingSourceCredential.objects.for_team(self.team.pk).exists()

    def test_store_credentials_rejects_invalid_config(self):
        response = self._store(source_type="Postgres", payload={"host": "localhost"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid source config" in response.json()["message"]
        assert not PendingSourceCredential.objects.for_team(self.team.pk).exists()

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source.StripeSource.validate_credentials",
        return_value=(True, None),
    )
    def test_stored_credentials_list_returns_metadata_only(self, _mock_validate):
        response = self._store()
        assert response.status_code == status.HTTP_201_CREATED

        list_response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/stored_credentials/")
        assert list_response.status_code == status.HTTP_200_OK
        results = list_response.json()
        assert len(results) == 1
        assert results[0]["credential_id"] == response.json()["credential_id"]
        assert results[0]["source_type"] == "Stripe"
        assert "sk_test_123" not in json.dumps(list_response.json())

    def test_stored_credentials_list_filters_by_source_type_and_hides_expired_and_other_teams(self):
        def _create(team, source_type, **kwargs):
            return PendingSourceCredential.objects.for_team(team.pk).create(
                team=team, source_type=source_type, payload={"key": "secret"}, **kwargs
            )

        stripe_credential = _create(self.team, "Stripe")
        _create(self.team, "Postgres")
        _create(self.team, "Stripe", expires_at=timezone.now() - timedelta(minutes=1))
        other_team = Team.objects.create(organization=self.organization, name="other")
        _create(other_team, "Stripe")

        response = self.client.get(
            f"/api/environments/{self.team.pk}/external_data_sources/stored_credentials/?source_type=Stripe"
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.json()
        assert [result["credential_id"] for result in results] == [str(stripe_credential.pk)]

    def test_stored_credentials_list_orders_newest_first(self):
        older = PendingSourceCredential.objects.for_team(self.team.pk).create(
            team=self.team, source_type="Stripe", payload={"key": "secret"}
        )
        newer = PendingSourceCredential.objects.for_team(self.team.pk).create(
            team=self.team, source_type="Stripe", payload={"key": "secret"}
        )
        PendingSourceCredential.objects.for_team(self.team.pk).filter(pk=older.pk).update(
            created_at=timezone.now() - timedelta(hours=1)
        )

        response = self.client.get(f"/api/environments/{self.team.pk}/external_data_sources/stored_credentials/")
        assert response.status_code == status.HTTP_200_OK
        assert [result["credential_id"] for result in response.json()] == [str(newer.pk), str(older.pk)]


_PREVIEW_MANIFEST = {
    "client": {
        "base_url": "https://api.example.com",
        "auth": {"type": "api_key", "name": "key", "location": "query"},
    },
    "resources": [
        {"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "data"}},
    ],
}


class TestExternalDataSourcePreviewAndCustomPayload(APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/environments/{self.team.pk}/external_data_sources/{action}/"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.preview_resource"
    )
    def test_preview_resource_happy_path(self, mock_preview):
        mock_preview.return_value = PreviewResult(
            rows=[{"id": 1, "name": "a"}],
            row_count=1,
            columns=[{"name": "id", "type": "integer"}, {"name": "name", "type": "string"}],
            error=None,
        )

        response = self.client.post(
            self._url("preview_resource"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST), "auth_api_key": "sk_test"},
                "resource_name": "users",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert body["row_count"] == 1
        assert body["rows"] == [{"id": 1, "name": "a"}]
        assert body["columns"] == [{"name": "id", "type": "integer"}, {"name": "name", "type": "string"}]
        assert body["error"] is None
        assert mock_preview.call_args.args[2] == "users"
        assert mock_preview.call_args.args[3] == PREVIEW_DEFAULT_ROWS

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.preview_resource"
    )
    def test_preview_resource_forwards_explicit_limit(self, mock_preview):
        mock_preview.return_value = PreviewResult(rows=[], row_count=0, columns=[], error=None)

        response = self.client.post(
            self._url("preview_resource"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST)},
                "resource_name": "users",
                "limit": 25,
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert mock_preview.call_args.args[3] == 25

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.preview_resource"
    )
    def test_preview_resource_manifest_error_returns_400(self, mock_preview):
        mock_preview.side_effect = ManifestValidationError("resources[0].endpoint.path: must not be empty")

        response = self.client.post(
            self._url("preview_resource"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST)},
                "resource_name": "users",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "must not be empty" in response.json()["message"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.preview_resource"
    )
    def test_preview_resource_fetch_error_returns_200_with_error(self, mock_preview):
        mock_preview.return_value = PreviewResult(rows=[], row_count=0, columns=[], error="could not reach host")

        response = self.client.post(
            self._url("preview_resource"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST)},
                "resource_name": "users",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["error"] == "could not reach host"
        assert response.json()["rows"] == []

    def test_preview_resource_non_custom_source_returns_400(self):
        response = self.client.post(
            self._url("preview_resource"),
            data={"source_type": "Stripe", "payload": {"api_key": "sk"}, "resource_name": "charges"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not supported" in response.json()["message"]

    def test_preview_resource_limit_over_cap_returns_400(self):
        response = self.client.post(
            self._url("preview_resource"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST)},
                "resource_name": "users",
                "limit": PREVIEW_MAX_ROWS + 1,
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_database_schema_accepts_custom_payload(self, _mock_validate):
        response = self.client.post(
            self._url("database_schema"),
            data={
                "source_type": "Custom",
                "manifest_json": json.dumps(_PREVIEW_MANIFEST),
                "auth_api_key": "sk_test",
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [table["table"] for table in response.json()] == ["users"]

    @patch(
        "products.data_warehouse.backend.presentation.views.external_data_source.trigger_external_data_source_workflow"
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.CustomSource.validate_credentials",
        return_value=(True, None),
    )
    def test_setup_accepts_custom_payload(self, _mock_validate, _mock_trigger):
        response = self.client.post(
            self._url("setup"),
            data={
                "source_type": "Custom",
                "payload": {"manifest_json": json.dumps(_PREVIEW_MANIFEST), "auth_api_key": "sk_test"},
                "prefix": "custom_preview_",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        source = ExternalDataSource.objects.get(id=response.json()["id"])
        assert source.source_type == "Custom"
        assert source.created_via == ExternalDataSource.CreatedVia.MCP


class TestGetDirectConnectionMetadata(SimpleTestCase):
    def _source_impl(self, error: Exception, non_retryable: dict | None = None) -> Mock:
        impl = Mock()
        impl.get_connection_metadata.side_effect = error
        impl.get_non_retryable_errors.return_value = non_retryable or {}
        return impl

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    def test_expected_connection_error_is_not_captured(self, mock_capture):
        # An unreachable customer host fails the best-effort metadata probe — already surfaced by
        # credential validation, so it must degrade to the fallback without flooding error tracking.
        impl = self._source_impl(
            psycopg.OperationalError('connection to server at "192.0.2.1", port 5432 failed: Network is unreachable')
        )
        fallback = {"database": "existing"}

        result = get_direct_connection_metadata(source_impl=impl, source_config=Mock(), team_id=1, fallback=fallback)

        self.assertEqual(result, fallback)
        mock_capture.assert_not_called()

    @patch("products.data_warehouse.backend.presentation.views.external_data_source.capture_exception")
    def test_unexpected_error_is_still_captured(self, mock_capture):
        error = ValueError("unexpected bug in metadata probe")
        impl = self._source_impl(error)

        result = get_direct_connection_metadata(source_impl=impl, source_config=Mock(), team_id=1, fallback=None)

        self.assertEqual(result, {})
        mock_capture.assert_called_once_with(error)
