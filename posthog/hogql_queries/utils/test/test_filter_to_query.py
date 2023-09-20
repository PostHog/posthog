import pytest
from posthog.hogql_queries.filter_to_query import filter_to_query
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.schema import ActionsNode, BaseMathType, CountPerActorMathType, EventsNode, PropertyMathType
from posthog.test.base import BaseTest
from posthog.models.filters.filter import Filter

insight_1 = {
    "events": [{"id": "signed_up", "type": "events", "order": 0}],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "week",
    "date_from": "-8w",
}
insight_2 = {
    "events": [{"id": "signed_up", "type": "events", "order": 0}],
    "actions": [],
    "display": "WorldMap",
    "insight": "TRENDS",
    "breakdown": "$geoip_country_code",
    "date_from": "-1m",
    "breakdown_type": "event",
}
insight_3 = {
    "events": [
        {"id": "signed_up", "name": "signed_up", "type": "events", "order": 2, "custom_name": "Signed up"},
        {"id": "upgraded_plan", "name": "upgraded_plan", "type": "events", "order": 4, "custom_name": "Upgraded plan"},
    ],
    "actions": [{"id": 1, "name": "Interacted with file", "type": "actions", "order": 3}],
    "display": "FunnelViz",
    "insight": "FUNNELS",
    "interval": "day",
    "date_from": "-1m",
    "funnel_viz_type": "steps",
    "filter_test_accounts": True,
}
insight_4 = {
    "period": "Week",
    "display": "ActionsTable",
    "insight": "RETENTION",
    "properties": {
        "type": "AND",
        "values": [
            {"type": "AND", "values": [{"key": "email", "type": "person", "value": "is_set", "operator": "is_set"}]}
        ],
    },
    "target_entity": {"id": "signed_up", "name": "signed_up", "type": "events", "order": 0},
    "retention_type": "retention_first_time",
    "total_intervals": 9,
    "returning_entity": {"id": 1, "name": "Interacted with file", "type": "actions", "order": 0},
}
insight_5 = {
    "events": [],
    "actions": [{"id": 1, "math": "total", "name": "Interacted with file", "type": "actions", "order": 0}],
    "compare": False,
    "display": "ActionsLineGraph",
    "insight": "LIFECYCLE",
    "interval": "day",
    "shown_as": "Lifecycle",
    "date_from": "-8w",
    "new_entity": [],
    "properties": [],
    "filter_test_accounts": True,
}
insight_6 = {
    "events": [
        {
            "id": "uploaded_file",
            "math": "sum",
            "name": "uploaded_file",
            "type": "events",
            "order": 0,
            "custom_name": "Uploaded bytes",
            "math_property": "file_size_b",
        },
        {
            "id": "deleted_file",
            "math": "sum",
            "name": "deleted_file",
            "type": "events",
            "order": 1,
            "custom_name": "Deleted bytes",
            "math_property": "file_size_b",
        },
    ],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "week",
    "date_from": "-8w",
    "new_entity": [],
    "properties": [],
    "filter_test_accounts": True,
}
insight_7 = {
    "events": [{"id": "paid_bill", "math": "sum", "type": "events", "order": 0, "math_property": "amount_usd"}],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "month",
    "date_from": "-6m",
}
insight_8 = {
    "events": [
        {
            "id": "paid_bill",
            "math": "unique_group",
            "name": "paid_bill",
            "type": "events",
            "order": 0,
            "math_group_type_index": 0,
        }
    ],
    "actions": [],
    "compare": True,
    "date_to": None,
    "display": "BoldNumber",
    "insight": "TRENDS",
    "interval": "day",
    "date_from": "-30d",
    "properties": [],
    "filter_test_accounts": True,
}
insight_9 = {
    "events": [{"id": "$pageview", "math": "total", "type": "events", "order": 0}],
    "actions": [],
    "display": "ActionsTable",
    "insight": "TRENDS",
    "interval": "day",
    "breakdown": "$current_url",
    "date_from": "-6m",
    "new_entity": [],
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [{"key": "$current_url", "type": "event", "value": "/files/", "operator": "not_icontains"}],
            }
        ],
    },
    "breakdown_type": "event",
}
insight_10 = {
    "events": [
        {
            "id": "$pageview",
            "name": "$pageview",
            "type": "events",
            "order": 0,
            "properties": [
                {"key": "$current_url", "type": "event", "value": "https://hedgebox.net/", "operator": "exact"}
            ],
            "custom_name": "Viewed homepage",
        },
        {
            "id": "$pageview",
            "name": "$pageview",
            "type": "events",
            "order": 1,
            "properties": [
                {"key": "$current_url", "type": "event", "value": "https://hedgebox.net/signup/", "operator": "regex"}
            ],
            "custom_name": "Viewed signup page",
        },
        {"id": "signed_up", "name": "signed_up", "type": "events", "order": 2, "custom_name": "Signed up"},
    ],
    "actions": [],
    "display": "FunnelViz",
    "insight": "FUNNELS",
    "interval": "day",
    "date_from": "-1m",
    "funnel_viz_type": "steps",
    "filter_test_accounts": True,
}
insight_11 = {
    "date_to": None,
    "insight": "PATHS",
    "date_from": "-30d",
    "edge_limit": 50,
    "properties": {"type": "AND", "values": []},
    "step_limit": 5,
    "start_point": "https://hedgebox.net/",
    "funnel_filter": {},
    "exclude_events": [],
    "path_groupings": ["/files/*"],
    "include_event_types": ["$pageview"],
    "local_path_cleaning_filters": [],
}
insight_12 = {
    "events": [
        {"id": "uploaded_file", "type": "events", "order": 0},
        {"id": "deleted_file", "type": "events", "order": 2},
        {"id": "downloaded_file", "type": "events", "order": 1},
    ],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "day",
    "date_from": "-30d",
}
insight_13 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "day",
    "date_from": "-30d",
    "filter_test_accounts": True,
}
insight_14 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "week",
    "date_from": "-90d",
    "filter_test_accounts": True,
}
insight_15 = {
    "period": "Week",
    "insight": "RETENTION",
    "target_entity": {"id": "$pageview", "type": "events"},
    "retention_type": "retention_first_time",
    "returning_entity": {"id": "$pageview", "type": "events"},
    "filter_test_accounts": True,
}
insight_16 = {
    "events": [{"id": "$pageview", "type": "events"}],
    "insight": "LIFECYCLE",
    "interval": "week",
    "shown_as": "Lifecycle",
    "date_from": "-30d",
    "entity_type": "events",
    "filter_test_accounts": True,
}
insight_17 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsBarValue",
    "insight": "TRENDS",
    "interval": "day",
    "breakdown": "$referring_domain",
    "date_from": "-14d",
    "breakdown_type": "event",
    "filter_test_accounts": True,
}
insight_18 = {
    "events": [
        {"id": "$pageview", "type": "events", "order": 0, "custom_name": "First page view"},
        {"id": "$pageview", "type": "events", "order": 1, "custom_name": "Second page view"},
        {"id": "$pageview", "type": "events", "order": 2, "custom_name": "Third page view"},
    ],
    "layout": "horizontal",
    "display": "FunnelViz",
    "insight": "FUNNELS",
    "interval": "day",
    "breakdown": "$browser",
    "exclusions": [],
    "breakdown_type": "event",
    "funnel_viz_type": "steps",
    "filter_test_accounts": True,
}

testdata = [
    insight_1,
    insight_2,
    insight_3,
    insight_4,
    insight_5,
    insight_6,
    insight_7,
    insight_8,
    insight_9,
    insight_10,
    insight_11,
    insight_12,
    insight_13,
    insight_14,
    insight_15,
    insight_16,
    insight_17,
    insight_18,
]


@pytest.mark.parametrize("data", testdata)
def test_base_insights(data):
    filter = Filter(data=data)
    filter_to_query(filter)


class TestFilterToQuery(BaseTest):
    def test_base_trend(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "TrendsQuery")

    def test_full_trend(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(
            query.model_dump(),
            {
                "kind": "TrendsQuery",
                "dateRange": {"date_from": "-7d", "date_to": None},
                "interval": "day",
                "series": [],
                "properties": None,
                "filterTestAccounts": False,
                "samplingFactor": None,
                "breakdown": None,
                "trendsFilter": None,
                "aggregation_group_type_index": None,
            },
        )

    def test_base_funnel(self):
        filter = Filter(data={"insight": "FUNNELS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "FunnelsQuery")

    def test_base_retention_query(self):
        filter = Filter(data={"insight": "RETENTION"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "RetentionQuery")

    def test_base_retention_query_from_retention_filter(self):
        filter = RetentionFilter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "RetentionQuery")

    def test_base_paths_query(self):
        filter = Filter(data={"insight": "PATHS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "PathsQuery")

    def test_base_path_query_from_path_filter(self):
        filter = PathFilter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "PathsQuery")

    def test_base_lifecycle_query(self):
        filter = Filter(data={"insight": "LIFECYCLE"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "LifecycleQuery")

    def test_base_stickiness_query(self):
        filter = Filter(data={"insight": "STICKINESS"})

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "StickinessQuery")

    def test_base_stickiness_query_from_stickiness_filter(self):
        filter = StickinessFilter(data={}, team=self.team)

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "StickinessQuery")

    def test_date_range_default(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.dateRange.date_from, "-7d")
        self.assertEqual(query.dateRange.date_to, None)

    def test_date_range_custom(self):
        filter = Filter(data={"date_from": "-14d", "date_to": "-7d"})

        query = filter_to_query(filter)

        self.assertEqual(query.dateRange.date_from, "-14d")
        self.assertEqual(query.dateRange.date_to, "-7d")

    def test_interval_default(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.interval, "day")

    def test_interval_custom(self):
        filter = Filter(data={"interval": "hour"})

        query = filter_to_query(filter)

        self.assertEqual(query.interval, "hour")

    def test_series_default(self):
        filter = Filter(data={})

        query = filter_to_query(filter)

        self.assertEqual(query.series, [])

    def test_series_custom(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview"}, {"id": "$pageview", "math": "dau"}],
                "actions": [{"id": 1}, {"id": 1, "math": "dau"}],
            }
        )

        query = filter_to_query(filter)

        self.assertEqual(
            query.series,
            [
                ActionsNode(id=1),
                ActionsNode(id=1, math=BaseMathType.dau),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="$pageview", name="$pageview", math=BaseMathType.dau),
            ],
        )

    def test_series_order(self):
        filter = Filter(
            data={
                "events": [{"id": "$pageview", "order": 1}, {"id": "$pageview", "math": "dau", "order": 2}],
                "actions": [{"id": 1, "order": 3}, {"id": 1, "math": "dau", "order": 0}],
            }
        )

        query = filter_to_query(filter)

        self.assertEqual(
            query.series,
            [
                ActionsNode(id=1, math=BaseMathType.dau),
                EventsNode(event="$pageview", name="$pageview"),
                EventsNode(event="$pageview", name="$pageview", math=BaseMathType.dau),
                ActionsNode(id=1),
            ],
        )

    def test_series_math(self):
        filter = Filter(
            data={
                "events": [
                    {"id": "$pageview", "math": "dau"},  # base math type
                    {"id": "$pageview", "math": "median", "math_property": "$math_prop"},  # property math type
                    {"id": "$pageview", "math": "avg_count_per_actor"},  # count per actor math type
                    {"id": "$pageview", "math": "unique_group", "math_group_type_index": 0},  # unique group
                    {
                        "id": "$pageview",
                        "math": "hogql",
                        "math_hogql": "avg(toInt(properties.$session_id)) + 1000",
                    },  # hogql
                ]
            }
        )

        query = filter_to_query(filter)

        self.assertEqual(
            query.series,
            [
                EventsNode(event="$pageview", name="$pageview", math=BaseMathType.dau),
                EventsNode(
                    event="$pageview", name="$pageview", math=PropertyMathType.median, math_property="$math_prop"
                ),
                EventsNode(event="$pageview", name="$pageview", math=CountPerActorMathType.avg_count_per_actor),
                EventsNode(event="$pageview", name="$pageview", math="unique_group", math_group_type_index=0),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    math="hogql",
                    math_hogql="avg(toInt(properties.$session_id)) + 1000",
                ),
            ],
        )

    def test_series_properties(self):
        pass  # TODO
