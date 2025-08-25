from posthog.test.base import BaseTest

from django.db.utils import IntegrityError

from posthog.models import Dashboard, Insight, Team
from posthog.models.insight import generate_insight_filters_hash


class TestInsightModel(BaseTest):
    def test_short_id_and_team_must_be_unique_together(self) -> None:
        Insight.objects.create(team=self.team, short_id="123456")

        # The same ID could in theory be reused by another team
        new_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(team=new_team, short_id="123456")

        count = Insight.objects.count()

        with self.assertRaises(IntegrityError):
            Insight.objects.create(team=self.team, short_id="123456")
            self.assertEqual(Insight.objects.count(), count)

    def test_short_id_is_automatically_generated(self) -> None:
        d = Insight.objects.create(team=self.team)
        self.assertRegex(d.short_id, r"[0-9A-Za-z_-]{8}")

    def test_dashboard_with_no_filters_does_not_override_date_from(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})
        filters_with_no_dashboard = insight.dashboard_filters(dashboard=None)

        filters_with_dashboard_with_no_date_from = insight.dashboard_filters(
            dashboard=(Dashboard.objects.create(team=self.team))
        )

        assert filters_with_no_dashboard["date_from"] == "-30d"
        assert filters_with_dashboard_with_no_date_from["date_to"] is None  # can be ignored if None
        del filters_with_dashboard_with_no_date_from["date_to"]
        assert filters_with_no_dashboard == filters_with_dashboard_with_no_date_from

    def test_dashboard_with_date_from_filters_does_override_date_from(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})

        filters_with_dashboard_with_different_date_from = insight.dashboard_filters(
            dashboard=(Dashboard.objects.create(team=self.team, filters={"date_from": "-14d"}))
        )

        assert filters_with_dashboard_with_different_date_from["date_from"] == "-14d"

    def test_dashboard_with_date_from_filters_does_override_date_to(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "2023-06-17", "date_to": "2023-06-25"})

        filters_with_dashboard_with_different_date_from = insight.dashboard_filters(
            dashboard=(Dashboard.objects.create(team=self.team, filters={"date_from": "-14d"}))
        )

        assert filters_with_dashboard_with_different_date_from["date_from"] == "-14d"
        assert filters_with_dashboard_with_different_date_from["date_to"] is None

    def test_dashboard_with_same_date_from_filters_generates_expected_date_from(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})

        filters_with_dashboard_with_same_date_from = insight.dashboard_filters(
            dashboard=(Dashboard.objects.create(team=self.team, filters={"date_from": "-30d"}))
        )

        assert filters_with_dashboard_with_same_date_from["date_from"] == "-30d"

    def test_dashboard_filters_works_with_null_properties(self) -> None:
        insight = Insight.objects.create(
            team=self.team, filters={"date_from": "-30d", "compare": True, "properties": None}
        )
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": "all", "properties": {"a": 1}})

        # Check that this doesn't throw an error
        insight.dashboard_filters(dashboard=dashboard)

    def test_dashboard_with_date_from_all_overrides_compare(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d", "compare": True})
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": "all"})

        filters = insight.dashboard_filters(dashboard=dashboard)

        assert filters["compare"] is None

    def test_dashboard_does_not_affect_filters_hash_with_absent_date_from(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})
        dashboard = Dashboard.objects.create(team=self.team, filters={})

        filters_hash_no_dashboard = generate_insight_filters_hash(insight, None)
        filters_hash_with_absent_date_from = generate_insight_filters_hash(insight, dashboard)

        assert filters_hash_no_dashboard == filters_hash_with_absent_date_from

    def test_dashboard_does_not_affect_filters_hash_with_null_date_from(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": None})

        filters_hash_no_dashboard = generate_insight_filters_hash(insight, None)
        filters_hash_with_null_date_from = generate_insight_filters_hash(insight, dashboard)

        assert filters_hash_no_dashboard == filters_hash_with_null_date_from

    def test_dashboard_with_date_from_changes_filters_hash(self) -> None:
        insight = Insight.objects.create(team=self.team, filters={"date_from": "-30d"})
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": "-90d"})

        filters_hash_one = generate_insight_filters_hash(insight, None)
        filters_hash_two = generate_insight_filters_hash(insight, dashboard)

        assert filters_hash_one != filters_hash_two

    def test_dashboard_with_query_insight_and_filters(self) -> None:
        browser_equals_firefox = {
            "key": "$browser",
            "label": None,
            "operator": "exact",
            "type": "event",
            "value": ["Firefox"],
        }
        browser_equals_chrome = {
            "key": "$browser",
            "label": None,
            "operator": "exact",
            "type": "event",
            "value": ["Chrome"],
        }

        # use test cases and a for loop because django TestCase doesn't have parametrization
        test_cases = [
            (
                # test that query filters are equal when there are no dashboard filters
                {"dateRange": {"date_from": "-14d", "date_to": "-7d"}},
                {},
                {
                    "dateRange": {
                        "date_from": "-14d",
                        "date_to": "-7d",
                    }
                },
            ),
            (
                # test that dashboard filters are used when there are no query filters
                {},
                {"date_from": "-14d", "date_to": "-7d"},
                {
                    "dateRange": {"date_from": "-14d", "date_to": "-7d", "explicitDate": False},
                    "filterTestAccounts": None,
                    "properties": None,
                },
            ),
            (
                # test that dashboard filters take priority
                {"dateRange": {"date_from": "-2d", "date_to": "-1d"}},
                {"date_from": "-4d", "date_to": "-3d"},
                {
                    "dateRange": {"date_from": "-4d", "date_to": "-3d", "explicitDate": False},
                    "filterTestAccounts": None,
                    "properties": None,
                },
            ),
            (
                # test that dashboard filters take priority, even if only one value is set, the other is set to None
                {"dateRange": {"date_from": "-14d", "date_to": "-7d"}},
                {"date_from": "all"},
                {
                    "dateRange": {"date_from": "all", "date_to": None, "explicitDate": False},
                    "filterTestAccounts": None,
                    "properties": None,
                },
            ),
            (
                # test that if no filters are set then none are outputted
                {},
                {},
                {},
            ),
            (
                # test that properties from the query are used when there are no dashboard properties
                {"properties": [browser_equals_firefox]},
                {},
                {
                    "properties": [browser_equals_firefox],
                },
            ),
            (
                # test that properties from the dashboard are used when there are no query properties
                {},
                {"properties": [browser_equals_chrome]},
                {
                    "dateRange": None,
                    "filterTestAccounts": None,
                    "properties": [browser_equals_chrome],
                },
            ),
            (
                # test that properties are merged when set in both query and dashboard
                {"properties": [browser_equals_firefox]},
                {"properties": [browser_equals_chrome]},
                {
                    "dateRange": None,
                    "filterTestAccounts": None,
                    "properties": [browser_equals_firefox, browser_equals_chrome],
                },
            ),
        ]

        for query_filters, dashboard_filters, expected_filters in test_cases:
            query_insight = Insight.objects.create(
                team=self.team,
                query={
                    "kind": "DataTableNode",
                    "source": {
                        "filters": query_filters,
                        "kind": "HogQLQuery",
                        "modifiers": None,
                        "query": "select * from events where {filters}",
                        "response": None,
                        "values": None,
                    },
                },
            )
            dashboard = Dashboard.objects.create(team=self.team, filters=dashboard_filters)

            data = query_insight.get_effective_query(dashboard=dashboard)
            assert data
            actual = data["source"]["filters"]
            assert expected_filters == actual
