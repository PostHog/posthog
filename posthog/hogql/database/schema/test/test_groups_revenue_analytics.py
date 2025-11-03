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

from django.utils.timezone import now

from dateutil.relativedelta import relativedelta

from posthog.schema import CurrencyCode, HogQLQueryModifiers, RevenueAnalyticsEventItem, RevenueCurrencyPropertyConfig

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping
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

    person_id = "00000000-0000-0000-0000-000000000000"
    group0_id = "lolol0:xxx"
    group1_id = "lolol1:xxx"
    another_group0_id = "lolol1:xxx2"
    distinct_id = "distinct_id"

    def tearDown(self):
        if hasattr(self, "invoices_cleanup_filesystem"):
            self.invoices_cleanup_filesystem()
        if hasattr(self, "customers_cleanup_filesystem"):
            self.customers_cleanup_filesystem()
        super().tearDown()

    def setup_events(self):
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=self.group0_id,
            properties={"industry": "positive"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key=self.another_group0_id,
            properties={"industry": "another"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=1,
            group_key=self.group1_id,
            properties={"industry": "negative"},
        )

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
            properties={"$group_0": self.group0_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 25042, "$group_0": self.group0_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 12500, "$group_1": self.group1_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 10000, "$group_0": self.group0_id, "$group_1": self.group1_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=self.QUERY_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 3223, "$group_0": self.another_group0_id},
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

        self._setup_join()
        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()

    def create_managed_viewsets(self):
        self.viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        self.viewset.sync_views()

    def _setup_join(self):
        # Create some mappings
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        GroupTypeMapping.objects.create(
            team=self.team, project_id=self.team.project_id, group_type="company", group_type_index=1
        )

        self.join = DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name=f"stripe.posthog_test.{SCHEMA.source_suffix}",
            source_table_key="id",
            joining_table_name="groups",
            joining_table_key="key",
            field_name="groups",
        )

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
                    "SELECT key, revenue_analytics.revenue, $virt_revenue FROM groups where key = {key}",
                    placeholders={"key": ast.Constant(value=self.group0_id)},
                ),
                self.team,
            )

            self.assertEqual(
                response.results,
                [("lolol0:xxx", Decimal("350.42"), Decimal("350.42"))],
            )

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
                        "SELECT key, revenue_analytics.revenue, $virt_revenue FROM groups where key = {key}",
                        placeholders={"key": ast.Constant(value=self.group0_id)},
                    ),
                    self.team,
                )

                self.assertEqual(
                    response.results,
                    [("lolol0:xxx", Decimal("350.42"), Decimal("350.42"))],
                )

    def test_get_revenue_for_schema_source_for_id_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        # These are the 6 IDs inside the CSV files, plus an extra dummy/empty one
        for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            queries = [
                "SELECT key, revenue_analytics.revenue FROM groups ORDER BY key ASC",
                "SELECT key, $virt_revenue FROM groups ORDER BY key ASC",
            ]

            for query in queries:
                response = execute_hogql_query(parse_select(query), self.team, modifiers=self.MODIFIERS)

                self.assertEqual(
                    response.results,
                    [
                        ("cus_1", Decimal("283.8496260553")),
                        ("cus_2", Decimal("482.2158673452")),
                        ("cus_3", Decimal("4161.34422")),
                        ("cus_4", Decimal("254.12345")),
                        ("cus_5", Decimal("1494.0562")),
                        ("cus_6", Decimal("2796.37014")),
                        ("dummy", None),
                    ],
                )

    def test_get_revenue_for_schema_source_for_id_join_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self.setup_schema_sources()
            self.join.source_table_key = "id"
            self.join.save()

            self.create_managed_viewsets()

            # These are the 6 IDs inside the CSV files, plus an extra dummy/empty one
            for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
                create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

            with freeze_time(self.QUERY_TIMESTAMP):
                queries = [
                    "SELECT key, revenue_analytics.revenue FROM groups ORDER BY key ASC",
                    "SELECT key, $virt_revenue FROM groups ORDER BY key ASC",
                ]

                for query in queries:
                    response = execute_hogql_query(parse_select(query), self.team, modifiers=self.MODIFIERS)

                    self.assertEqual(
                        response.results,
                        [
                            ("cus_1", Decimal("283.8496260553")),
                            ("cus_2", Decimal("482.2158673452")),
                            ("cus_3", Decimal("4161.34422")),
                            ("cus_4", Decimal("254.12345")),
                            ("cus_5", Decimal("1494.0562")),
                            ("cus_6", Decimal("2796.37014")),
                            ("dummy", None),
                        ],
                    )

    def test_get_revenue_for_schema_source_for_email_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "email"
        self.join.save()

        # These are the 6 IDs inside the CSV files, and we have an extra empty one
        for key in [
            "john.doe@example.com",  # cus_1
            "jane.doe@example.com",  # cus_2
            "john.smith@example.com",  # cus_3
            "jane.smith@example.com",  # cus_4
            "john.doejr@example.com",  # cus_5
            "john.doejrjr@example.com",  # cus_6
            "zdummy",
        ]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select("SELECT key, revenue_analytics.revenue, $virt_revenue FROM groups ORDER BY key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    ("jane.doe@example.com", Decimal("482.2158673452"), Decimal("482.2158673452")),
                    ("jane.smith@example.com", Decimal("254.12345"), Decimal("254.12345")),
                    ("john.doe@example.com", Decimal("283.8496260553"), Decimal("283.8496260553")),
                    ("john.doejr@example.com", Decimal("1494.0562"), Decimal("1494.0562")),
                    ("john.doejrjr@example.com", Decimal("2796.37014"), Decimal("2796.37014")),
                    ("john.smith@example.com", Decimal("4161.34422"), Decimal("4161.34422")),
                    ("zdummy", None, None),
                ],
            )

    def test_get_revenue_for_schema_source_for_metadata_join(self):
        self.setup_schema_sources()
        self.join.source_table_key = "JSONExtractString(metadata, 'id')"
        self.join.save()

        # These are the 6 IDs inside the CSV files, and we have an extra empty one
        for key in [
            "cus_1_metadata",
            "cus_2_metadata",
            "cus_3_metadata",
            "cus_4_metadata",
            "cus_5_metadata",
            "cus_6_metadata",
            "dummy",
        ]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select("SELECT key, revenue_analytics.revenue, $virt_revenue FROM groups ORDER BY key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    ("cus_1_metadata", Decimal("283.8496260553"), Decimal("283.8496260553")),
                    ("cus_2_metadata", Decimal("482.2158673452"), Decimal("482.2158673452")),
                    ("cus_3_metadata", Decimal("4161.34422"), Decimal("4161.34422")),
                    ("cus_4_metadata", Decimal("254.12345"), Decimal("254.12345")),
                    ("cus_5_metadata", Decimal("1494.0562"), Decimal("1494.0562")),
                    ("cus_6_metadata", Decimal("2796.37014"), Decimal("2796.37014")),
                    ("dummy", None, None),
                ],
            )

    def test_query_revenue_analytics_table_sources(self):
        self.setup_schema_sources()
        self.join.source_table_key = "email"
        self.join.save()

        # These are the 6 IDs inside the CSV files, and we have an extra empty one
        for key in [
            "john.doe@example.com",  # cus_1
            "jane.doe@example.com",  # cus_2
            "john.smith@example.com",  # cus_3
            "jane.smith@example.com",  # cus_4
            "john.doejr@example.com",  # cus_5
            "john.doejrjr@example.com",  # cus_6
            "zdummy",
        ]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            results = execute_hogql_query(
                parse_select("SELECT * FROM groups_revenue_analytics ORDER BY group_key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                results.results,
                [
                    ("jane.doe@example.com", Decimal("482.2158673452"), ANY),
                    ("jane.smith@example.com", Decimal("254.12345"), ANY),
                    ("john.doe@example.com", Decimal("283.8496260553"), ANY),
                    ("john.doejr@example.com", Decimal("1494.0562"), ANY),
                    ("john.doejrjr@example.com", Decimal("2796.37014"), ANY),
                    ("john.smith@example.com", Decimal("4161.34422"), ANY),
                ],
            )

    def test_query_revenue_analytics_table_events(self):
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
            results = execute_hogql_query(
                parse_select("SELECT * FROM groups_revenue_analytics ORDER BY group_key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                results.results,
                [
                    ("lolol0:xxx", Decimal("350.42"), None),
                    ("lolol1:xxx", Decimal("225"), None),
                    ("lolol1:xxx2", Decimal("32.23"), None),
                ],
            )

    def test_query_revenue_analytics_table_events_with_managed_viewsets_ff(self):
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
                results = execute_hogql_query(
                    parse_select("SELECT * FROM groups_revenue_analytics ORDER BY group_key ASC"),
                    self.team,
                    modifiers=self.MODIFIERS,
                )

                self.assertEqual(
                    results.results,
                    [
                        ("lolol0:xxx", Decimal("350.42"), None),
                        ("lolol1:xxx", Decimal("225"), None),
                        ("lolol1:xxx2", Decimal("32.23"), None),
                    ],
                )

    # Basic regression test when grouping on events only
    def test_basic_events(self):
        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.distinct_id,
            timestamp=now() - relativedelta(hours=1),
            properties={self.REVENUE_PROPERTY: 25042, "$group_0": self.group0_id},
        )

        with freeze_time(self.QUERY_TIMESTAMP):
            results = execute_hogql_query(
                parse_select("SELECT * FROM groups_revenue_analytics ORDER BY group_key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                results.results,
                [(self.group0_id, Decimal("25042"), Decimal("25042"))],
            )
