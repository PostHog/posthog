from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models.insight import Insight

from ee.api.test.base import LicensedTestMixin


class TestInsight(ClickhouseTestMixin, LicensedTestMixin, APIBaseTest, QueryMatchingTest):
    maxDiff = None

    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    def test_can_save_valid_events_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {
                "name": "Insight with events query",
                "query": {
                    "kind": "EventsQuery",
                    "select": [
                        "*",
                        "event",
                        "person",
                        "coalesce(properties.$current_url, properties.$screen_name)",
                        "properties.$lib",
                        "timestamp",
                    ],
                    "properties": [
                        {
                            "type": "event",
                            "key": "$browser",
                            "operator": "exact",
                            "value": "Chrome",
                        }
                    ],
                    "limit": 100,
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )

    def test_can_save_valid_events_table_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {
                "name": "Insight with events table query",
                "query": {
                    "kind": "DataTableNode",
                    "source": {
                        "kind": "EventsQuery",
                        "select": [
                            "*",
                            "event",
                            "person",
                            "coalesce(properties.$current_url, properties.$screen_name)",
                            "properties.$lib",
                            "timestamp",
                        ],
                        "properties": [
                            {
                                "type": "event",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                        "limit": 100,
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )

    def test_can_save_valid_persons_table_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "columns": ["person", "id", "created_at", "person.$delete"],
                    "source": {
                        "kind": "EventsQuery",
                        "select": ["*"],
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )

    def test_no_default_filters_on_insight_query(self) -> None:
        _, insight_json = self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "columns": ["person", "id", "created_at", "person.$delete"],
                    "source": {
                        "kind": "EventsQuery",
                        "select": ["*"],
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )
        assert insight_json["filters"] == {}

    def test_can_save_insights_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {
                "name": "Insight with insights query",
                "query": {
                    "kind": "TrendsQuery",
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "OR",
                                "values": [
                                    {
                                        "type": "event",
                                        "key": "$current_url",
                                        "operator": "exact",
                                        "value": ["https://hedgebox.net/files/"],
                                    },
                                    {
                                        "type": "event",
                                        "key": "$geoip_country_code",
                                        "operator": "exact",
                                        "value": ["US", "AU"],
                                    },
                                ],
                            }
                        ],
                    },
                    "filterTestAccounts": False,
                    "interval": "day",
                    "dateRange": {"date_from": "-7d"},
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "$pageview",
                            "custom_name": "Views",
                            "event": "$pageview",
                            "limit": 100,
                        }
                    ],
                    "trendsFilter": {"display": "ActionsAreaGraph"},
                    "breakdownFilter": {
                        "breakdown": "$geoip_country_code",
                        "breakdown_type": "event",
                    },
                },
            },
        )

    def test_cannot_save_a_completely_invalid_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {"name": "Insight with events query", "query": "not a valid query"},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

    def test_cannot_save_invalid_persons_table_query_to_an_insight(self) -> None:
        self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "source": {
                        "kind": "EventsQuery",
                        "select": ["*"],
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )

    def test_can_list_insights_including_those_with_only_queries(self) -> None:
        self.dashboard_api.create_insight({"name": "Insight with filters"})
        self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "columns": ["person", "id", "created_at", "person.$delete"],
                    "source": {
                        "kind": "EventsQuery",
                        "select": ["*"],
                    },
                },
            },
        )

        created_insights: list[Insight] = list(Insight.objects.all())
        assert len(created_insights) == 2

        listed_insights = self.dashboard_api.list_insights()
        assert listed_insights["count"] == 2

    @parameterized.expand(
        [
            (
                "already_wrapped_insight_viz_node",
                {
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}],
                        "dateRange": {"date_from": "-7d"},
                        "interval": "day",
                    },
                },
                "InsightVizNode",
                None,
            ),
            (
                "raw_trends_query",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "name": "$pageview"}],
                    "dateRange": {"date_from": "-7d"},
                    "interval": "day",
                },
                "InsightVizNode",
                "TrendsQuery",
            ),
            (
                "raw_hogql_query",
                {"kind": "HogQLQuery", "query": "select event from events limit 1"},
                "DataVisualizationNode",
                "HogQLQuery",
            ),
            (
                "already_wrapped_data_visualization_node",
                {
                    "kind": "DataVisualizationNode",
                    "source": {"kind": "HogQLQuery", "query": "select event from events limit 1"},
                },
                "DataVisualizationNode",
                "HogQLQuery",
            ),
        ]
    )
    def test_mcp_create_normalizes_query(self, _name, query, expected_kind, expected_source_kind) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            data={"name": "Test insight", "favorited": False, "saved": True, "query": query},
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["query"]["kind"] == expected_kind
        if expected_source_kind is not None:
            assert response.json()["query"]["source"]["kind"] == expected_source_kind

    def test_mcp_create_rejects_disallowed_query_kind(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/",
            data={
                "name": "Unsupported insight",
                "favorited": False,
                "saved": True,
                "query": {
                    "kind": "ErrorTrackingQuery",
                    "dateRange": {"date_from": "-7d"},
                    "orderBy": "last_seen",
                    "volumeResolution": 60,
                },
            },
            HTTP_X_POSTHOG_CLIENT="mcp",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error_body = str(response.json())
        assert "This query can't be saved" in error_body
        assert "Traceback" not in error_body
