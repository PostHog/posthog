from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, snapshot_clickhouse_queries

from posthog.schema import (
    CurrencyCode,
    RevenueAnalyticsEventItem,
    RevenueCurrencyPropertyConfig,
    SubscriptionDropoffMode,
)

from posthog.hogql import ast
from posthog.hogql.database.schema.test.base import RevenueAnalyticsManagedViewsetsTestMixin, RevenueAnalyticsTestBase
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group
from posthog.models.group_type_mapping import GroupTypeMapping

from products.data_warehouse.backend.models import DataWarehouseJoin
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA


class TestGroupsRevenueAnalyticsMixin(RevenueAnalyticsTestBase):
    group0_id = "lolol0:xxx"
    group1_id = "lolol1:xxx"
    another_group0_id = "lolol1:xxx2"

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
            uuid=self.PERSON_ID,
            team_id=self.team.pk,
            distinct_ids=[self.DISTINCT_ID],
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={"$group_0": self.group0_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 25042, "$group_0": self.group0_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 12500, "$group_1": self.group1_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 10000, "$group_0": self.group0_id, "$group_1": self.group1_id},
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 3223, "$group_0": self.another_group0_id},
        )

    def setup_events_with_subscriptions(self):
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
            uuid=self.PERSON_ID,
            team_id=self.team.pk,
            distinct_ids=[self.DISTINCT_ID],
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={"$group_0": self.group0_id},
        )

        # Non-recurring event (no subscription_id)
        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={self.REVENUE_PROPERTY: 25042, "$group_0": self.group0_id},
        )

        # Recurring events (with subscription_id) - contributes to MRR
        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={
                self.REVENUE_PROPERTY: 12500,
                "$group_1": self.group1_id,
                self.SUBSCRIPTION_PROPERTY: "sub_1",
            },
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={
                self.REVENUE_PROPERTY: 10000,
                "$group_0": self.group0_id,
                "$group_1": self.group1_id,
                self.SUBSCRIPTION_PROPERTY: "sub_2",
            },
        )

        _create_event(
            event=self.PURCHASE_EVENT_NAME,
            team=self.team,
            distinct_id=self.DISTINCT_ID,
            timestamp=self.EVENT_TIMESTAMP,
            properties={
                self.REVENUE_PROPERTY: 3223,
                "$group_0": self.another_group0_id,
                self.SUBSCRIPTION_PROPERTY: "sub_3",
            },
        )

    def setup_schema_sources(self):
        self.create_sources()
        self._setup_join()
        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()

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


@snapshot_clickhouse_queries
class TestGroupsRevenueAnalytics(TestGroupsRevenueAnalyticsMixin):
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
                "SELECT key, properties.$virt_revenue FROM groups ORDER BY key ASC",
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

    def test_get_mrr_via_lazy_join_for_schema_source(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select(
                    "SELECT key, revenue_analytics.revenue, revenue_analytics.mrr FROM groups ORDER BY key ASC"
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    ("cus_1", Decimal("283.8496260553"), Decimal("22.9631447238")),
                    ("cus_2", Decimal("482.2158673452"), Decimal("40.8052916666")),
                    ("cus_3", Decimal("4161.34422"), Decimal("1546.59444")),
                    ("cus_4", Decimal("254.12345"), Decimal("83.16695")),
                    ("cus_5", Decimal("1494.0562"), Decimal("43.82703")),
                    ("cus_6", Decimal("2796.37014"), Decimal("1459.02008")),
                    ("dummy", None, None),
                ],
            )

    def test_get_mrr_via_lazy_join_for_events(self):
        self.setup_events_with_subscriptions()

        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
                currencyAwareDecimal=True,
                subscriptionProperty=self.SUBSCRIPTION_PROPERTY,
                subscriptionDropoffMode=SubscriptionDropoffMode.AFTER_DROPOFF_PERIOD,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select(
                    "SELECT key, revenue_analytics.revenue, revenue_analytics.mrr FROM groups WHERE key = {key}",
                    placeholders={"key": ast.Constant(value=self.group0_id)},
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [(self.group0_id, Decimal("350.42"), Decimal("257.23"))],
            )

    def test_query_revenue_analytics_table_sources(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        # These are the 6 IDs inside the CSV files
        for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6"]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        with freeze_time(self.QUERY_TIMESTAMP):
            results = execute_hogql_query(
                parse_select("SELECT group_key, revenue, mrr FROM groups_revenue_analytics ORDER BY mrr DESC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            # MRR values come from the MRR view based on recurring invoices with subscriptions
            self.assertEqual(
                results.results,
                [
                    ("cus_3", Decimal("4161.34422"), Decimal("1546.59444")),
                    ("cus_6", Decimal("2796.37014"), Decimal("1459.02008")),
                    ("cus_4", Decimal("254.12345"), Decimal("83.16695")),
                    ("cus_5", Decimal("1494.0562"), Decimal("43.82703")),
                    ("cus_2", Decimal("482.2158673452"), Decimal("40.8052916666")),
                    ("cus_1", Decimal("283.8496260553"), Decimal("22.9631447238")),
                ],
            )

    def test_query_revenue_analytics_table_events(self):
        self.setup_events_with_subscriptions()

        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
                currencyAwareDecimal=True,
                subscriptionProperty=self.SUBSCRIPTION_PROPERTY,
                subscriptionDropoffMode=SubscriptionDropoffMode.AFTER_DROPOFF_PERIOD,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        with freeze_time(self.QUERY_TIMESTAMP):
            results = execute_hogql_query(
                parse_select("SELECT group_key, revenue, mrr FROM groups_revenue_analytics ORDER BY group_key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            # MRR is calculated from recurring events (those with subscription_id)
            self.assertEqual(
                results.results,
                [
                    (self.group0_id, Decimal("350.42"), Decimal("257.23")),
                    (self.group1_id, Decimal("225"), Decimal("257.23")),
                    (self.another_group0_id, Decimal("32.23"), Decimal("257.23")),
                ],
            )


class TestGroupsRevenueAnalyticsManagedViewsets(
    TestGroupsRevenueAnalyticsMixin, RevenueAnalyticsManagedViewsetsTestMixin
):
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

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
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

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
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

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
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

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
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

    def test_get_mrr_via_lazy_join_for_schema_source(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6", "dummy"]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
            response = execute_hogql_query(
                parse_select(
                    "SELECT key, revenue_analytics.revenue, revenue_analytics.mrr FROM groups ORDER BY key ASC"
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [
                    ("cus_1", Decimal("283.8496260553"), Decimal("22.9631447238")),
                    ("cus_2", Decimal("482.2158673452"), Decimal("40.8052916666")),
                    ("cus_3", Decimal("4161.34422"), Decimal("1546.59444")),
                    ("cus_4", Decimal("254.12345"), Decimal("83.16695")),
                    ("cus_5", Decimal("1494.0562"), Decimal("43.82703")),
                    ("cus_6", Decimal("2796.37014"), Decimal("1459.02008")),
                    ("dummy", None, None),
                ],
            )

    def test_get_mrr_via_lazy_join_for_events(self):
        self.setup_events_with_subscriptions()

        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
                currencyAwareDecimal=True,
                subscriptionProperty=self.SUBSCRIPTION_PROPERTY,
                subscriptionDropoffMode=SubscriptionDropoffMode.AFTER_DROPOFF_PERIOD,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
            response = execute_hogql_query(
                parse_select(
                    "SELECT key, revenue_analytics.revenue, revenue_analytics.mrr FROM groups WHERE key = {key}",
                    placeholders={"key": ast.Constant(value=self.group0_id)},
                ),
                self.team,
                modifiers=self.MODIFIERS,
            )

            self.assertEqual(
                response.results,
                [(self.group0_id, Decimal("350.42"), Decimal("257.23"))],
            )

    def test_query_revenue_analytics_table_sources(self):
        self.setup_schema_sources()
        self.join.source_table_key = "id"
        self.join.save()

        # These are the 6 IDs inside the CSV files
        for key in ["cus_1", "cus_2", "cus_3", "cus_4", "cus_5", "cus_6"]:
            create_group(team_id=self.team.pk, group_type_index=0, group_key=key)

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
            results = execute_hogql_query(
                parse_select("SELECT group_key, revenue, mrr FROM groups_revenue_analytics ORDER BY mrr DESC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            # MRR values from managed viewsets
            self.assertEqual(
                results.results,
                [
                    ("cus_3", Decimal("4161.34422"), Decimal("1546.59444")),
                    ("cus_6", Decimal("2796.37014"), Decimal("1459.02008")),
                    ("cus_4", Decimal("254.12345"), Decimal("83.16695")),
                    ("cus_5", Decimal("1494.0562"), Decimal("43.82703")),
                    ("cus_2", Decimal("482.2158673452"), Decimal("40.8052916666")),
                    ("cus_1", Decimal("283.8496260553"), Decimal("22.9631447238")),
                ],
            )

    def test_query_revenue_analytics_table_events(self):
        self.setup_events_with_subscriptions()

        self.team.revenue_analytics_config.events = [
            RevenueAnalyticsEventItem(
                eventName=self.PURCHASE_EVENT_NAME,
                revenueProperty=self.REVENUE_PROPERTY,
                revenueCurrencyProperty=RevenueCurrencyPropertyConfig(static="USD"),
                currencyAwareDecimal=True,
                subscriptionProperty=self.SUBSCRIPTION_PROPERTY,
                subscriptionDropoffMode=SubscriptionDropoffMode.AFTER_DROPOFF_PERIOD,
            )
        ]
        self.team.revenue_analytics_config.save()
        self.team.save()

        self.create_and_materialize_viewsets()
        with freeze_time(self.QUERY_TIMESTAMP), self.snapshot_select_queries():
            results = execute_hogql_query(
                parse_select("SELECT group_key, revenue, mrr FROM groups_revenue_analytics ORDER BY group_key ASC"),
                self.team,
                modifiers=self.MODIFIERS,
            )

            # MRR is calculated from recurring events (those with subscription_id)
            self.assertEqual(
                results.results,
                [
                    (self.group0_id, Decimal("350.42"), Decimal("257.23")),
                    (self.group1_id, Decimal("225"), Decimal("257.23")),
                    (self.another_group0_id, Decimal("32.23"), Decimal("257.23")),
                ],
            )
