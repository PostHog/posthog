import uuid
from pathlib import Path
from decimal import Decimal
from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query
from posthog.schema import (
    CurrencyCode,
    HogQLQueryModifiers,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
)
from posthog.warehouse.models import ExternalDataSchema
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_person,
    _create_event,
)

from posthog.temporal.data_imports.pipelines.stripe.constants import (
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
)
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_INVOICE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
)

INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_customers"


class TestRevenueAnalytics(ClickhouseTestMixin, APIBaseTest):
    PURCHASE_EVENT_NAME = "purchase"
    REVENUE_PROPERTY = "revenue"
    QUERY_TIMESTAMP = "2025-05-30"

    def tearDown(self):
        if hasattr(self, "invoices_cleanup_filesystem"):
            self.invoices_cleanup_filesystem()
        if hasattr(self, "customers_cleanup_filesystem"):
            self.customers_cleanup_filesystem()
        super().tearDown()

    def test_get_revenue_for_events(self):
        person_id = str(uuid.uuid4())

        _create_person(
            uuid=person_id,
            team_id=self.team.pk,
            distinct_ids=[person_id],
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=person_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 10000},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=person_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 25042},
        )

        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
                currencyAwareDecimal=True,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        with freeze_time(self.QUERY_TIMESTAMP):
            queries = [
                "select revenue_analytics.revenue from persons where id = {person_id}",
                "select $virt_revenue from persons where id = {person_id}",
            ]
            for query in queries:
                response = execute_hogql_query(
                    parse_select(query, placeholders={"person_id": ast.Constant(value=person_id)}),
                    self.team,
                )

                assert response.results[0][0] == Decimal("350.42")

    def test_get_revenue_for_schema_source(self):
        # These are the 6 IDs inside the CSV files
        for person_id in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6"]:
            _create_person(team_id=self.team.pk, distinct_ids=[person_id])

        invoices_csv_path = Path("products/revenue_analytics/backend/hogql_queries/test/data/stripe_invoices.csv")
        invoices_table, source, credential, _, self.invoices_cleanup_filesystem = create_data_warehouse_table_from_csv(
            invoices_csv_path,
            "stripe_invoice",
            STRIPE_INVOICE_COLUMNS,
            INVOICES_TEST_BUCKET,
            self.team,
        )

        customers_csv_path = Path("products/revenue_analytics/backend/hogql_queries/test/data/stripe_customers.csv")
        customers_table, _, _, _, self.customers_cleanup_filesystem = create_data_warehouse_table_from_csv(
            customers_csv_path,
            "stripe_customer",
            STRIPE_CUSTOMER_COLUMNS,
            CUSTOMERS_TEST_BUCKET,
            self.team,
            source=source,
            credential=credential,
        )

        # Besides the default creations above, also create the external data schema
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        _invoices_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=source,
            table=invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        _customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CUSTOMER_RESOURCE_NAME,
            source=source,
            table=customers_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()

        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True)
            queries = [
                "select revenue_analytics.customer_id, revenue_analytics.revenue from persons order by id asc",
                "select revenue_analytics.customer_id, $virt_revenue from persons order by id asc",
            ]
            for query in queries:
                response = execute_hogql_query(
                    parse_select(query),
                    self.team,
                    modifiers=modifiers,
                )

                assert response.results == [
                    ("cus_1", Decimal("429.7424")),
                    ("cus_2", Decimal("287.4779")),
                    ("cus_3", Decimal("26182.78099")),
                    ("cus_4", Decimal("254.12345")),
                    ("cus_5", Decimal("626.83253")),
                    ("cus_6", Decimal("17476.47254")),
                ]
