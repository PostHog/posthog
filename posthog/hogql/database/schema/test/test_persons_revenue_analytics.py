from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import ANY, patch

from parameterized import parameterized

from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.temporal.data_imports.sources.stripe.constants import (
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)

from products.data_warehouse.backend.models import DataWarehouseJoin, ExternalDataSchema
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
)
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA

INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_customers"


@snapshot_clickhouse_queries
class TestRevenueAnalytics(ClickhouseTestMixin, APIBaseTest):
    PURCHASE_EVENT_NAME = "purchase"
    REVENUE_PROPERTY = "revenue"
    QUERY_TIMESTAMP = "2025-05-30"
    MODIFIERS = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True)

    def tearDown(self):
        if hasattr(self, "invoices_cleanup_filesystem"):
            self.invoices_cleanup_filesystem()
        if hasattr(self, "customers_cleanup_filesystem"):
            self.customers_cleanup_filesystem()
        super().tearDown()

    def setup_events(self):
        self.person_id = "00000000-0000-0000-0000-000000000000"
        self.distinct_id = "distinct_id"

        _create_person(
            uuid=self.person_id,
            team_id=self.team.pk,
            distinct_ids=[self.distinct_id],
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 10000},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 25042},
        )

    def setup_schema_sources(self):
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

        self.join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=f"stripe.posthog_test.{SCHEMA.source_suffix}",
            source_table_key="id",
            joining_table_name="persons",
            joining_table_key="pdi.distinct_id",
            field_name="persons",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()

    def create_managed_viewsets(self):
        self.viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        self.viewset.sync_views()

    def test_get_revenue_for_events(self):
        self.setup_events()

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
            response = execute_hogql_query(
                parse_select(
                    "select revenue_analytics.revenue, $virt_revenue from persons where id = {id}",
                    placeholders={"id": ast.Constant(value=self.person_id)},
                ),
                self.team,
            )

            self.assertEqual(response.results[0], (Decimal("350.42"), Decimal("350.42")))

    def test_get_revenue_for_events_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.setup_events()

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
            self.create_managed_viewsets()

            with freeze_time(self.QUERY_TIMESTAMP):
                response = execute_hogql_query(
                    parse_select(
                        "select revenue_analytics.revenue, $virt_revenue from persons where id = {id}",
                        placeholders={"id": ast.Constant(value=self.person_id)},
                    ),
                    self.team,
                )

                self.assertEqual(response.results[0], (Decimal("350.42"), Decimal("350.42")))

    def test_get_revenue_for_schema_source_for_id_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        # These are the 6 IDs inside the CSV files, plus an extra dummy/empty one
        distinct_id_to_person_id: dict[str, str] = {}
        for distinct_id in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
            person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            distinct_id_to_person_id[distinct_id] = person.uuid

        with freeze_time(self.QUERY_TIMESTAMP):
            queries = [
                "SELECT id, revenue_analytics.revenue from persons order by id asc",
                "SELECT id, $virt_revenue from persons order by id asc",
            ]

            for query in queries:
                response = execute_hogql_query(parse_select(query), self.team, modifiers=self.MODIFIERS)

                self.assertEqual(
                    response.results,
                    [
                        (distinct_id_to_person_id["cus_1"], Decimal("283.8496260553")),
                        (distinct_id_to_person_id["cus_2"], Decimal("482.2158673452")),
                        (distinct_id_to_person_id["cus_3"], Decimal("4161.34422")),
                        (distinct_id_to_person_id["cus_4"], Decimal("254.12345")),
                        (distinct_id_to_person_id["cus_5"], Decimal("1494.0562")),
                        (distinct_id_to_person_id["cus_6"], Decimal("2796.37014")),
                        (distinct_id_to_person_id["dummy"], None),
                    ],
                )

    def test_get_revenue_for_schema_source_for_id_join_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.setup_schema_sources()

            self.join.source_table_key = "id"
            self.join.save()

            self.create_managed_viewsets()

            # These are the 6 IDs inside the CSV files, plus an extra dummy/empty one
            distinct_id_to_person_id: dict[str, str] = {}
            for distinct_id in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
                person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                distinct_id_to_person_id[distinct_id] = person.uuid

            with freeze_time(self.QUERY_TIMESTAMP):
                queries = [
                    "SELECT id, revenue_analytics.revenue from persons order by id asc",
                    "SELECT id, $virt_revenue from persons order by id asc",
                ]

                for query in queries:
                    response = execute_hogql_query(parse_select(query), self.team, modifiers=self.MODIFIERS)

                    self.assertEqual(
                        response.results,
                        [
                            (distinct_id_to_person_id["cus_1"], Decimal("283.8496260553")),
                            (distinct_id_to_person_id["cus_2"], Decimal("482.2158673452")),
                            (distinct_id_to_person_id["cus_3"], Decimal("4161.34422")),
                            (distinct_id_to_person_id["cus_4"], Decimal("254.12345")),
                            (distinct_id_to_person_id["cus_5"], Decimal("1494.0562")),
                            (distinct_id_to_person_id["cus_6"], Decimal("2796.37014")),
                            (distinct_id_to_person_id["dummy"], None),
                        ],
                    )

    def test_get_revenue_for_schema_source_for_email_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "email"
        self.join.save()

        # These are the 6 IDs inside the CSV files, and we have an extra empty one
        distinct_id_to_person_id: dict[str, str] = {}
        for distinct_id in [
            "john.doe@example.com",  # cus_1
            "jane.doe@example.com",  # cus_2
            "john.smith@example.com",  # cus_3
            "jane.smith@example.com",  # cus_4
            "john.doejr@example.com",  # cus_5
            "john.doejrjr@example.com",  # cus_6
            "zdummy",
        ]:
            person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            distinct_id_to_person_id[distinct_id] = person.uuid

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select("SELECT id, revenue_analytics.revenue, $virt_revenue FROM persons ORDER BY id ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    (
                        distinct_id_to_person_id["john.doe@example.com"],
                        Decimal("283.8496260553"),
                        Decimal("283.8496260553"),
                    ),
                    (
                        distinct_id_to_person_id["jane.doe@example.com"],
                        Decimal("482.2158673452"),
                        Decimal("482.2158673452"),
                    ),
                    (distinct_id_to_person_id["john.smith@example.com"], Decimal("4161.34422"), Decimal("4161.34422")),
                    (distinct_id_to_person_id["jane.smith@example.com"], Decimal("254.12345"), Decimal("254.12345")),
                    (distinct_id_to_person_id["john.doejr@example.com"], Decimal("1494.0562"), Decimal("1494.0562")),
                    (
                        distinct_id_to_person_id["john.doejrjr@example.com"],
                        Decimal("2796.37014"),
                        Decimal("2796.37014"),
                    ),
                    (distinct_id_to_person_id["zdummy"], None, None),
                ],
            )

    def test_get_revenue_for_schema_source_for_metadata_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "JSONExtractString(metadata, 'id')"
        self.join.save()

        # These are the 6 IDs inside the CSV files, and we have an extra empty one
        distinct_id_to_person_id: dict[str, str] = {}
        for distinct_id in [
            "cus_1_metadata",
            "cus_2_metadata",
            "cus_3_metadata",
            "cus_4_metadata",
            "cus_5_metadata",
            "cus_6_metadata",
            "dummy",
        ]:
            person = _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            distinct_id_to_person_id[distinct_id] = person.uuid

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select("SELECT id, revenue_analytics.revenue, $virt_revenue from persons order by id asc"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    (distinct_id_to_person_id["cus_1_metadata"], Decimal("283.8496260553"), Decimal("283.8496260553")),
                    (distinct_id_to_person_id["cus_2_metadata"], Decimal("482.2158673452"), Decimal("482.2158673452")),
                    (distinct_id_to_person_id["cus_3_metadata"], Decimal("4161.34422"), Decimal("4161.34422")),
                    (distinct_id_to_person_id["cus_4_metadata"], Decimal("254.12345"), Decimal("254.12345")),
                    (distinct_id_to_person_id["cus_5_metadata"], Decimal("1494.0562"), Decimal("1494.0562")),
                    (distinct_id_to_person_id["cus_6_metadata"], Decimal("2796.37014"), Decimal("2796.37014")),
                    (distinct_id_to_person_id["dummy"], None, None),
                ],
            )

    def test_get_revenue_for_schema_source_for_customer_with_multiple_distinct_ids(self):
        self.setup_schema_sources()
        self.join.source_table_key = "email"
        self.join.save()

        # Person has several distinct IDs, but only one of them can be matched from the customer table
        multiple_distinct_ids_person = _create_person(
            team_id=self.team.pk, distinct_ids=["distinct_1", "john.doe@example.com"]
        )

        # Dummy person without revenue
        dummy_person = _create_person(team_id=self.team.pk, distinct_ids=["dummy"])

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select("SELECT id, $virt_revenue FROM persons ORDER BY $virt_revenue ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    (multiple_distinct_ids_person.uuid, Decimal("283.8496260553")),
                    (dummy_person.uuid, None),
                ],
            )

            response = execute_hogql_query(
                parse_select("SELECT $virt_revenue FROM persons ORDER BY $virt_revenue ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(response.results, [(Decimal("283.8496260553"),), (None,)])

    def test_query_revenue_analytics_table(self):
        self.setup_schema_sources()
        self.join.source_table_key = "email"
        self.join.save()

        with freeze_time(self.QUERY_TIMESTAMP):
            results = execute_hogql_query(
                parse_select("SELECT * FROM persons_revenue_analytics ORDER BY person_id ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(results.results, [(ANY, Decimal("9471.9595034005"), ANY)])

    @parameterized.expand([e.value for e in PersonsOnEventsMode])
    def test_virtual_property_in_trend(self, mode):
        self.setup_events()

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

        # Breaking down by revenue doesnt make any sense, but this is just proving it works
        with freeze_time(self.QUERY_TIMESTAMP):
            query = TrendsQuery(
                **{
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview", "math": "total"}],
                    "trendsFilter": {},
                    "breakdownFilter": {"breakdowns": [{"property": "$virt_revenue", "type": "person"}]},
                },
                dateRange=DateRange(date_from="all", date_to=None),
                modifiers=HogQLQueryModifiers(personsOnEventsMode=mode),
            )
            tqr = TrendsQueryRunner(team=self.team, query=query)
            results = tqr.calculate().results

        assert results[0]["breakdown_value"] == ["350.42"]

    @parameterized.expand([e.value for e in PersonsOnEventsMode])
    def test_virtual_property_in_trend_with_managed_viewsets_ff(self, mode):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.setup_events()

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

            self.create_managed_viewsets()

            # Breaking down by revenue doesnt make any sense, but this is just proving it works
            with freeze_time(self.QUERY_TIMESTAMP):
                query = TrendsQuery(
                    **{
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "name": "$pageview", "event": "$pageview", "math": "total"}],
                        "trendsFilter": {},
                        "breakdownFilter": {"breakdowns": [{"property": "$virt_revenue", "type": "person"}]},
                    },
                    dateRange=DateRange(date_from="all", date_to=None),
                    modifiers=HogQLQueryModifiers(personsOnEventsMode=mode),
                )
                tqr = TrendsQueryRunner(team=self.team, query=query)
                results = tqr.calculate().results

            assert results[0]["breakdown_value"] == ["350.42"]
