from typing import List

from rest_framework import status

from ee.api.test.base import LicensedTestMixin
from posthog.api.test.dashboards import DashboardAPI
from posthog.models.insight import Insight
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest


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
                        "coalesce(properties.$current_url, properties.$screen_name) # Url / Screen",
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
                            "coalesce(properties.$current_url, properties.$screen_name) # Url / Screen",
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
                        "kind": "PersonsNode",
                        "properties": [
                            {
                                "type": "person",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
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
                        "kind": "PersonsNode",
                        "properties": [
                            {
                                "type": "person",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )
        assert insight_json["filters"] == {}

    def test_default_filters_on_non_query_insight(self) -> None:
        _, insight_json = self.dashboard_api.create_insight(
            {
                "name": "Old-Fashioned Insight",
                "filters": {
                    "events": [
                        {"id": "$pageview"},
                    ],
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )
        assert insight_json["filters"] == {
            "events": [
                {"id": "$pageview"},
            ],
            "insight": "TRENDS",
            "date_from": "-7d",
        }

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
                            "properties": [
                                {
                                    "type": "event",
                                    "key": "$browser",
                                    "operator": "exact",
                                    "value": "Chrome",
                                },
                                {"type": "cohort", "key": "id", "value": 2},
                            ],
                            "limit": 100,
                        }
                    ],
                    "trendsFilter": {"display": "ActionsAreaGraph"},
                    "breakdown": {
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
                        "kind": "PersonsNode",
                        "properties": [
                            {
                                "type": "person",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                    },
                },
            },
            expected_status=status.HTTP_201_CREATED,
        )

    def test_listing_insights_by_default_does_not_include_those_with_only_queries(self) -> None:
        self.dashboard_api.create_insight({"name": "Insight with filters"})
        self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "columns": ["person", "id", "created_at", "person.$delete"],
                    "source": {
                        "kind": "PersonsNode",
                        "properties": [
                            {
                                "type": "person",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                    },
                },
            },
        )

        created_insights: List[Insight] = list(Insight.objects.all())
        assert len(created_insights) == 2

        listed_insights = self.dashboard_api.list_insights(query_params={"include_query_insights": False})
        assert listed_insights["count"] == 1
        assert listed_insights["results"][0]["name"] == "Insight with filters"

    def test_can_list_insights_including_those_with_only_queries(self) -> None:
        self.dashboard_api.create_insight({"name": "Insight with filters"})
        self.dashboard_api.create_insight(
            {
                "name": "Insight with persons table query",
                "query": {
                    "kind": "DataTableNode",
                    "columns": ["person", "id", "created_at", "person.$delete"],
                    "source": {
                        "kind": "PersonsNode",
                        "properties": [
                            {
                                "type": "person",
                                "key": "$browser",
                                "operator": "exact",
                                "value": "Chrome",
                            }
                        ],
                    },
                },
            },
        )

        created_insights: List[Insight] = list(Insight.objects.all())
        assert len(created_insights) == 2

        listed_insights = self.dashboard_api.list_insights(query_params={"include_query_insights": True})
        assert listed_insights["count"] == 2
