import csv
import tempfile
from datetime import datetime
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.models import (
    DataWarehouseManagedViewSet,
    DataWarehouseSavedQuery,
    ExternalDataSchema,
)
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)

TEST_BUCKET_BASE = "test_storage_bucket"
INVOICES_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
CUSTOMERS_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_customers"
SUBSCRIPTIONS_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_subscriptions"
CHARGES_TEST_BUCKET = f"{TEST_BUCKET_BASE}-posthog.revenue_analytics.insights_query_runner.stripe_charges"
_TEST_DATA_DIR = (
    Path(__file__).resolve().parents[5]
    / "products"
    / "revenue_analytics"
    / "backend"
    / "hogql_queries"
    / "test"
    / "data"
)


class RevenueAnalyticsTestBase(ClickhouseTestMixin, BaseTest):
    PURCHASE_EVENT_NAME = "purchase"
    REVENUE_PROPERTY = "revenue"
    SUBSCRIPTION_PROPERTY = "subscription_id"
    QUERY_TIMESTAMP = "2025-05-30"
    EVENT_TIMESTAMP = "2025-05-29"  # One day before the query timestamp
    MODIFIERS = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True)
    PERSON_ID = "00000000-0000-0000-0000-000000000000"
    DISTINCT_ID = "distinct_id"

    _TABLE_CONFIGS: dict[str, tuple[str, dict, str, str]] = {
        "invoice": ("stripe_invoices", STRIPE_INVOICE_COLUMNS, INVOICES_TEST_BUCKET, STRIPE_INVOICE_RESOURCE_NAME),
        "customer": ("stripe_customers", STRIPE_CUSTOMER_COLUMNS, CUSTOMERS_TEST_BUCKET, STRIPE_CUSTOMER_RESOURCE_NAME),
        "subscription": (
            "stripe_subscriptions",
            STRIPE_SUBSCRIPTION_COLUMNS,
            SUBSCRIPTIONS_TEST_BUCKET,
            STRIPE_SUBSCRIPTION_RESOURCE_NAME,
        ),
        "charge": ("stripe_charges", STRIPE_CHARGE_COLUMNS, CHARGES_TEST_BUCKET, STRIPE_CHARGE_RESOURCE_NAME),
    }

    def tearDown(self):
        for cleanup in getattr(self, "_source_cleanups", []):
            cleanup()
        super().tearDown()

    def create_source_table(self, key: str) -> None:
        csv_name, columns, bucket, schema_name = self._TABLE_CONFIGS[key]

        table, source, credential, _, cleanup = create_data_warehouse_table_from_csv(
            _TEST_DATA_DIR / f"{csv_name}.csv",
            f"stripe_{key}",
            columns,
            bucket,
            self.team,
            source=getattr(self, "source", None),
            credential=getattr(self, "_credential", None),
        )

        if not hasattr(self, "source"):
            self.source = source
        self._credential = credential

        if not hasattr(self, "_source_cleanups"):
            self._source_cleanups = []
        self._source_cleanups.append(cleanup)

        ExternalDataSchema.objects.create(
            team=self.team,
            name=schema_name,
            source=self.source,
            table=table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

    def create_sources(self):
        self.create_source_table("invoice")
        self.create_source_table("customer")


class RevenueAnalyticsManagedViewsetsTestMixin(RevenueAnalyticsTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.mock_flag = patch("posthoganalytics.feature_enabled", return_value=True)
        self.mock_flag.start()

    def tearDown(self) -> None:
        self.mock_flag.stop()
        if hasattr(self, "_materialized_cleanups"):
            for cleanup in self._materialized_cleanups:
                cleanup()
        if hasattr(self, "_temp_csv_files"):
            for csv_path in self._temp_csv_files:
                csv_path.unlink(missing_ok=True)
        super().tearDown()

    def create_and_materialize_viewsets(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
                team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
            )
            viewset.sync_views()
            materialization_csvs = self._get_materialization_csvs()
        self._upload_materialized_csvs(materialization_csvs)

    def _get_materialization_csvs(self):
        materialization_csvs = []
        for saved_query in DataWarehouseSavedQuery.objects.filter(
            team=self.team, managed_viewset__isnull=False
        ).order_by("name"):
            query_text = saved_query.query.get("query", "") if isinstance(saved_query.query, dict) else ""
            if not query_text:
                continue

            response = execute_hogql_query(parse_select(query_text), team=self.team, modifiers=self.MODIFIERS)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(response.columns or [])
                for row in response.results or []:
                    writer.writerow(
                        [value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value for value in row]
                    )
                csv_path = Path(csv_file.name)

            nullable_columns = {}
            for col_name, col_def in (saved_query.columns or {}).items():
                if isinstance(col_def, dict):
                    ch_type = col_def["clickhouse"]
                    if not ch_type.startswith("Nullable("):
                        col_def = {**col_def, "clickhouse": f"Nullable({ch_type})"}
                nullable_columns[col_name] = col_def

            materialization_csvs.append((saved_query, csv_path, nullable_columns))

        return materialization_csvs

    def _upload_materialized_csvs(self, materialization_csvs):
        self._materialized_cleanups = []
        for saved_query, csv_path, nullable_columns in materialization_csvs:
            table, _, _, _, cleanup = create_data_warehouse_table_from_csv(
                csv_path,
                saved_query.name,
                nullable_columns,
                f"{TEST_BUCKET_BASE}-{saved_query.name.replace('.', '_')}",
                self.team,
                source_prefix="",
            )
            self._materialized_cleanups.append(cleanup)
            saved_query.table = table
            saved_query.is_materialized = True
            saved_query.save()
