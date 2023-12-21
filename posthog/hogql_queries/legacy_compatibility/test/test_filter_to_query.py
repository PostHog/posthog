import pytest
from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema import (
    ActionsNode,
    AggregationAxisFormat,
    BaseMathType,
    BreakdownAttributionType,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    CohortPropertyFilter,
    CountPerActorMathType,
    ElementPropertyFilter,
    EntityType,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusion,
    FunnelPathType,
    FunnelVizType,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    Key,
    PathCleaningFilter,
    PathType,
    PersonPropertyFilter,
    PropertyMathType,
    PropertyOperator,
    RetentionPeriod,
    RetentionType,
    SessionPropertyFilter,
    StepOrderValue,
    TrendsFilter,
    FunnelsFilter,
    RetentionFilter,
    PathsFilter,
    StickinessFilter,
)
from posthog.test.base import BaseTest


insight_0 = {
    "events": [{"id": "signed_up", "type": "events", "order": 0}],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "week",
    "date_from": "-8w",
}
insight_1 = {
    "events": [{"id": "signed_up", "type": "events", "order": 0}],
    "actions": [],
    "display": "WorldMap",
    "insight": "TRENDS",
    "breakdown": "$geoip_country_code",
    "date_from": "-1m",
    "breakdown_type": "event",
}
insight_2 = {
    "events": [
        {
            "id": "signed_up",
            "name": "signed_up",
            "type": "events",
            "order": 2,
            "custom_name": "Signed up",
        },
        {
            "id": "upgraded_plan",
            "name": "upgraded_plan",
            "type": "events",
            "order": 4,
            "custom_name": "Upgraded plan",
        },
    ],
    "actions": [{"id": 1, "name": "Interacted with file", "type": "actions", "order": 3}],
    "display": "FunnelViz",
    "insight": "FUNNELS",
    "interval": "day",
    "date_from": "-1m",
    "funnel_viz_type": "steps",
    "filter_test_accounts": True,
}
insight_3 = {
    "period": "Week",
    "display": "ActionsTable",
    "insight": "RETENTION",
    "properties": {
        "type": "AND",
        "values": [
            {
                "type": "AND",
                "values": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": "is_set",
                        "operator": "is_set",
                    }
                ],
            }
        ],
    },
    "target_entity": {
        "id": "signed_up",
        "name": "signed_up",
        "type": "events",
        "order": 0,
    },
    "retention_type": "retention_first_time",
    "total_intervals": 9,
    "returning_entity": {
        "id": 1,
        "name": "Interacted with file",
        "type": "actions",
        "order": 0,
    },
}
insight_4 = {
    "events": [],
    "actions": [
        {
            "id": 1,
            "math": "total",
            "name": "Interacted with file",
            "type": "actions",
            "order": 0,
        }
    ],
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
insight_5 = {
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
insight_6 = {
    "events": [
        {
            "id": "paid_bill",
            "math": "sum",
            "type": "events",
            "order": 0,
            "math_property": "amount_usd",
        }
    ],
    "actions": [],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "month",
    "date_from": "-6m",
}
insight_7 = {
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
insight_8 = {
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
                "values": [
                    {
                        "key": "$current_url",
                        "type": "event",
                        "value": "/files/",
                        "operator": "not_icontains",
                    }
                ],
            }
        ],
    },
    "breakdown_type": "event",
}
insight_9 = {
    "events": [
        {
            "id": "$pageview",
            "name": "$pageview",
            "type": "events",
            "order": 0,
            "properties": [
                {
                    "key": "$current_url",
                    "type": "event",
                    "value": "https://hedgebox.net/",
                    "operator": "exact",
                }
            ],
            "custom_name": "Viewed homepage",
        },
        {
            "id": "$pageview",
            "name": "$pageview",
            "type": "events",
            "order": 1,
            "properties": [
                {
                    "key": "$current_url",
                    "type": "event",
                    "value": "https://hedgebox.net/signup/",
                    "operator": "regex",
                }
            ],
            "custom_name": "Viewed signup page",
        },
        {
            "id": "signed_up",
            "name": "signed_up",
            "type": "events",
            "order": 2,
            "custom_name": "Signed up",
        },
    ],
    "actions": [],
    "display": "FunnelViz",
    "insight": "FUNNELS",
    "interval": "day",
    "date_from": "-1m",
    "funnel_viz_type": "steps",
    "filter_test_accounts": True,
}
insight_10 = {
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
insight_11 = {
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
insight_12 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "day",
    "date_from": "-30d",
    "filter_test_accounts": True,
}
insight_13 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "week",
    "date_from": "-90d",
    "filter_test_accounts": True,
}
insight_14 = {
    "period": "Week",
    "insight": "RETENTION",
    "target_entity": {"id": "$pageview", "type": "events"},
    "retention_type": "retention_first_time",
    "returning_entity": {"id": "$pageview", "type": "events"},
    "filter_test_accounts": True,
}
insight_15 = {
    "events": [{"id": "$pageview", "type": "events"}],
    "insight": "LIFECYCLE",
    "interval": "week",
    "shown_as": "Lifecycle",
    "date_from": "-30d",
    "entity_type": "events",
    "filter_test_accounts": True,
}
insight_16 = {
    "events": [{"id": "$pageview", "math": "dau", "type": "events"}],
    "display": "ActionsBarValue",
    "insight": "TRENDS",
    "interval": "day",
    "breakdown": "$referring_domain",
    "date_from": "-14d",
    "breakdown_type": "event",
    "filter_test_accounts": True,
}
insight_17 = {
    "events": [
        {
            "id": "$pageview",
            "type": "events",
            "order": 0,
            "custom_name": "First page view",
        },
        {
            "id": "$pageview",
            "type": "events",
            "order": 1,
            "custom_name": "Second page view",
        },
        {
            "id": "$pageview",
            "type": "events",
            "order": 2,
            "custom_name": "Third page view",
        },
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
insight_18 = {
    "events": [
        {
            "id": "$pageview",
            "math": None,
            "name": "$pageview",
            "type": "events",
            "order": None,
            "math_hogql": None,
            "properties": {},
            "custom_name": None,
            "math_property": None,
            "math_group_type_index": None,
        }
    ],
    "display": "ActionsLineGraph",
    "insight": "LIFECYCLE",
    "interval": "day",
    "date_from": "-7d",
    "sampling_factor": "",
    "smoothing_intervals": 1,
    "breakdown_normalize_url": False,
    "breakdown_attribution_type": "first_touch",
}

# real world regression tests
insight_19 = {
    "actions": [
        {
            "id": 2760,
            "math": "total",
            "name": "Pageviews",
            "type": "actions",
            "order": 0,
            "properties": [
                {
                    "key": "$browser",
                    "type": "event",
                    "value": "Chrome",
                    "operator": None,
                }
            ],
            "math_property": None,
        }
    ],
    "display": "ActionsBar",
    "insight": "LIFECYCLE",
    "interval": "day",
    "shown_as": "Lifecycle",
}
insight_20 = {
    "events": [
        {
            "id": "created change",
            "math": "total",
            "name": "created change",
            "type": "events",
            "order": 0,
            "properties": [{"key": "id", "type": "cohort", "value": 2208, "operator": None}],
            "custom_name": None,
            "math_property": None,
        }
    ],
    "display": "ActionsLineGraph",
    "insight": "LIFECYCLE",
    "interval": "day",
    "shown_as": "Lifecycle",
}
insight_21 = {
    "events": [
        {
            "id": "$pageview",
            "math": "total",
            "name": "$pageview",
            "type": "events",
            "order": 0,
            "properties": [],
            "math_property": None,
        }
    ],
    "display": "ActionsLineGraph",
    "insight": "LIFECYCLE",
    "interval": "day",
    "shown_as": "Lifecycle",
    "properties": [{"key": "id", "type": "cohort", "value": 929, "operator": "exact"}],
}
insight_22 = {
    "actions": [
        {
            "id": 4317,
            "math": "total",
            "name": "Some name",
            "type": "actions",
            "order": 0,
            "properties": [],
            "custom_name": None,
            "math_property": None,
        }
    ],
    "display": "ActionsLineGraph",
    "insight": "LIFECYCLE",
    "interval": "day",
    "shown_as": "Lifecycle",
    "properties": [{"key": "id", "type": "precalculated-cohort", "value": 760, "operator": None}],
    "funnel_window_days": 14,
}
insight_23 = {
    "actions": [
        {
            "id": "10184",
            "math": None,
            "name": "Some name",
            "type": "actions",
            "order": 0,
            "properties": [],
            "math_property": None,
        }
    ],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "day",
    "breakdown_type": "undefined",
}
insight_24 = {
    "events": [{"id": "$pageview", "name": "$pageview", "type": "events", "order": 0}],
    "display": "ActionsLineGraph",
    "insight": "TRENDS",
    "interval": "day",
    "shown_as": "Volume",
    "breakdown": False,
    "properties": [
        {
            "key": "$current_url",
            "type": "event",
            "value": "https://example.com/",
            "operator": "icontains",
        }
    ],
    "breakdown_type": "undefined",
}
insight_25 = {
    "events": [
        {
            "id": "$pageview",
            "math": None,
            "name": "$pageview",
            "type": "events",
            "order": 0,
            "properties": [],
            "math_property": None,
        }
    ],
    "display": "ActionsLineGrap[…]ccounts=false",
    "insight": "TRENDS",
    "interval": "day",
    "date_from": "-90d",
}
insight_26 = {
    "events": [
        {
            "id": "$pageview",
            "math": None,
            "name": "$pageview",
            "type": "events",
            "order": 2,
            "properties": [{"key": "$host", "type": "event", "value": [None], "operator": "exact"}],
            "math_property": None,
        },
    ],
    "insight": "TRENDS",
}
insight_27 = {
    "events": [
        {
            "id": "$pageview",
            "name": "$pageview",
            "type": "events",
        },
    ],
    "insight": "TRENDS",
}
insight_28 = {
    "actions": [
        {
            "id": None,
            "math": None,
            "name": None,
            "type": "actions",
            "order": None,
            "properties": [],
            "math_property": None,
        }
    ],
    "insight": "TRENDS",
}
insight_29 = {
    "events": [
        {
            "id": "$pageview",
            "type": "events",
        }
    ],
    "insight": "TRENDS",
    "breakdown": [None],
    "breakdown_type": "cohort",
}
insight_30 = {
    "events": [
        "{EXAMPLE_VARIABLE}",
        {
            "id": "$pageview",
            "math": "dau",
            "name": "$pageview",
            "type": "events",
            "order": 1,
            "properties": [
                {
                    "key": "$current_url",
                    "type": "event",
                    "value": "posthog.com/signup$",
                    "operator": "regex",
                }
            ],
            "custom_name": "Views on signup page",
        },
    ],
    "insight": "TRENDS",
}
insight_31 = {
    "events": [
        {
            "id": "$pageview",
            "name": "$pageview",
        }
    ],
    "insight": "TRENDS",
    "breakdown": "$geoip_country_code",
    "breakdown_type": "events",
    "breakdown_group_type_index": 0,
}
insight_32 = {
    "events": [
        {
            "id": "$autocapture",
            "math": "total",
            "name": "$autocapture",
            "type": "events",
            "order": 0,
        }
    ],
    "insight": "STICKINESS",
    "entity_type": "events",
}
insight_33 = {
    "events": [
        {
            "id": "$pageview",
            "math": "dau",
            "name": "$pageview",
            "type": "events",
            "order": None,
            "properties": [],
            "math_property": None,
        }
    ],
    "insight": "STICKINESS",
    "interval": "minute",
    "shown_as": "Stickiness",
    "date_from": "dStart",
}
insight_34 = {
    "period": "Week",
    "display": "ActionsTable",
    "insight": "RETENTION",
    "properties": [
        {"key": "id", "type": "precalculated-cohort", "value": 71, "operator": None},
        {"key": "id", "type": "static-cohort", "value": 696, "operator": None},
    ],
    "target_entity": {
        "id": 4912,
        "math": None,
        "name": None,
        "type": "actions",
        "order": None,
        "properties": [],
        "custom_name": None,
        "math_property": None,
    },
    "retention_type": "retention_first_time",
    "total_intervals": 11,
    "returning_entity": {
        "id": 3410,
        "math": None,
        "name": None,
        "type": "actions",
        "order": None,
        "properties": [],
        "custom_name": None,
        "math_property": None,
    },
}


test_insights = [
    insight_0,
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
    insight_19,
    insight_20,
    insight_21,
    insight_22,
    insight_23,
    insight_24,
    insight_25,
    insight_26,
    insight_27,
    insight_28,
    insight_29,
    insight_30,
    insight_31,
    insight_32,
    insight_33,
    insight_34,
]


@pytest.mark.parametrize("filter", test_insights)
def test_base_insights(filter: dict):
    filter_to_query(filter)


properties_0 = []
properties_1 = [{"key": "account_id", "type": "event", "value": ["some_id"], "operator": "exact"}]
properties_2 = [
    {"key": "account_id", "type": "event", "value": ["some_id"], "operator": "exact"},
    {
        "key": "$current_url",
        "type": "event",
        "value": "/path",
        "operator": "not_icontains",
    },
]
properties_3 = {}
properties_4 = {"type": "AND", "values": []}
properties_5 = {"type": "AND", "values": [{"type": "AND", "values": []}]}
properties_6 = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [
                {
                    "key": "$current_url",
                    "type": "event",
                    "value": "?",
                    "operator": "not_icontains",
                },
                {
                    "key": "$referring_domain",
                    "type": "event",
                    "value": "google",
                    "operator": "icontains",
                },
            ],
        }
    ],
}
properties_7 = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [{"type": "AND", "values": []}, {"type": "AND", "values": []}],
        },
        {
            "type": "AND",
            "values": [
                {
                    "key": "dateDiff('minute', timestamp, now()) < 5",
                    "type": "hogql",
                    "value": None,
                }
            ],
        },
    ],
}
properties_8 = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [
                {
                    "key": "dateDiff('minute', timestamp, now()) < 5",
                    "type": "hogql",
                    "value": None,
                }
            ],
        },
        {
            "type": "AND",
            "values": [
                {
                    "key": "dateDiff('minute', timestamp, now()) < 5",
                    "type": "hogql",
                    "value": None,
                }
            ],
        },
    ],
}
properties_9 = {
    "type": "AND",
    "values": [
        {
            "type": "AND",
            "values": [
                {
                    "key": "$browser",
                    "value": ["Chrome"],
                    "operator": "exact",
                    "type": "event",
                },
                {
                    "key": "$browser",
                    "value": ["Chrome"],
                    "operator": "exact",
                    "type": "person",
                },
                {
                    "key": "$feature/hogql-insights",
                    "value": ["true"],
                    "operator": "exact",
                    "type": "event",
                },
                {
                    "key": "site_url",
                    "value": ["http://localhost:8000"],
                    "operator": "exact",
                    "type": "group",
                    "group_type_index": 1,
                },
                {"key": "id", "value": 2, "type": "cohort"},
                {
                    "key": "tag_name",
                    "value": ["elem"],
                    "operator": "exact",
                    "type": "element",
                },
                {
                    "key": "$session_duration",
                    "value": None,
                    "operator": "gt",
                    "type": "session",
                },
                {"type": "hogql", "key": "properties.name", "value": None},
            ],
        },
        {"type": "OR", "values": [{}]},
    ],
}
properties_10 = [{"key": "id", "type": "cohort", "value": 71, "operator": None}]
properties_11 = [{"key": [498], "type": "cohort", "value": 498, "operator": None}]
properties_12 = [
    {
        "key": "userId",
        "type": "event",
        "values": ["63ffaeae99ac3c4240976d60"],
        "operator": "exact",
    }
]
properties_13 = {"plan": "premium"}
properties_14 = {"$current_url__icontains": "signin"}

test_properties = [
    properties_0,
    properties_1,
    properties_2,
    properties_3,
    properties_4,
    properties_5,
    properties_6,
    properties_7,
    properties_8,
    properties_9,
    properties_10,
    properties_11,
    properties_12,
    properties_13,
    properties_14,
]


@pytest.mark.parametrize("properties", test_properties)
def test_base_properties(properties):
    """smoke test (i.e. filter_to_query should not throw) for real world properties"""
    filter_to_query({"properties": properties})


class TestFilterToQuery(BaseTest):
    def test_base_trend(self):
        filter = {}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "TrendsQuery")

    def test_full_trend(self):
        filter = {}

        query = filter_to_query(filter)

        self.assertEqual(
            query.model_dump(exclude_defaults=True),
            {"series": []},
        )

    def test_base_funnel(self):
        filter = {"insight": "FUNNELS"}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "FunnelsQuery")

    def test_base_retention_query(self):
        filter = {"insight": "RETENTION", "retention_type": "retention_first_time"}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "RetentionQuery")

    def test_base_paths_query(self):
        filter = {"insight": "PATHS"}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "PathsQuery")

    def test_base_lifecycle_query(self):
        filter = {"insight": "LIFECYCLE"}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "LifecycleQuery")

    def test_base_stickiness_query(self):
        filter = {"insight": "STICKINESS"}

        query = filter_to_query(filter)

        self.assertEqual(query.kind, "StickinessQuery")

    def test_date_range(self):
        filter = {"date_from": "-14d", "date_to": "-7d"}

        query = filter_to_query(filter)

        self.assertEqual(query.dateRange.date_from, "-14d")
        self.assertEqual(query.dateRange.date_to, "-7d")

    def test_interval(self):
        filter = {"interval": "hour"}

        query = filter_to_query(filter)

        self.assertEqual(query.interval, "hour")

    def test_series_default(self):
        filter = {}

        query = filter_to_query(filter)

        self.assertEqual(query.series, [])

    def test_series_custom(self):
        filter = {
            "events": [{"id": "$pageview"}, {"id": "$pageview", "math": "dau"}],
            "actions": [{"id": 1}, {"id": 1, "math": "dau"}],
        }

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
        filter = {
            "events": [
                {"id": "$pageview", "order": 1},
                {"id": "$pageview", "math": "dau", "order": 2},
            ],
            "actions": [{"id": 1, "order": 3}, {"id": 1, "math": "dau", "order": 0}],
        }

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
        filter = {
            "events": [
                {"id": "$pageview", "math": "dau"},  # base math type
                {
                    "id": "$pageview",
                    "math": "median",
                    "math_property": "$math_prop",
                },  # property math type
                {
                    "id": "$pageview",
                    "math": "avg_count_per_actor",
                },  # count per actor math type
                {
                    "id": "$pageview",
                    "math": "unique_group",
                    "math_group_type_index": 0,
                },  # unique group
                {
                    "id": "$pageview",
                    "math": "hogql",
                    "math_hogql": "avg(toInt(properties.$session_id)) + 1000",
                },  # hogql
            ]
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.series,
            [
                EventsNode(event="$pageview", name="$pageview", math=BaseMathType.dau),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    math=PropertyMathType.median,
                    math_property="$math_prop",
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    math=CountPerActorMathType.avg_count_per_actor,
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    math="unique_group",
                    math_group_type_index=0,
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    math="hogql",
                    math_hogql="avg(toInt(properties.$session_id)) + 1000",
                ),
            ],
        )

    def test_series_properties(self):
        filter = {
            "events": [
                {"id": "$pageview", "properties": []},  # smoke test
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "success",
                            "type": "event",
                            "value": ["true"],
                            "operator": "exact",
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "is_set",
                            "operator": "is_set",
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "text",
                            "value": ["some text"],
                            "operator": "exact",
                            "type": "element",
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "$session_duration",
                            "value": 1,
                            "operator": "gt",
                            "type": "session",
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [{"key": "id", "value": 2, "type": "cohort"}],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "name",
                            "value": ["Hedgebox Inc."],
                            "operator": "exact",
                            "type": "group",
                            "group_type_index": 2,
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "dateDiff('minute', timestamp, now()) < 30",
                            "type": "hogql",
                            "value": None,
                        }
                    ],
                },
                {
                    "id": "$pageview",
                    "properties": [
                        {
                            "key": "$referring_domain",
                            "type": "event",
                            "value": "google",
                            "operator": "icontains",
                        },
                        {
                            "key": "utm_source",
                            "type": "event",
                            "value": "is_not_set",
                            "operator": "is_not_set",
                        },
                    ],
                },
            ]
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.series,
            [
                EventsNode(event="$pageview", name="$pageview", properties=[]),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[
                        EventPropertyFilter(
                            key="success",
                            value=["true"],
                            operator=PropertyOperator.exact,
                        )
                    ],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[
                        PersonPropertyFilter(
                            key="email",
                            value="is_set",
                            operator=PropertyOperator.is_set,
                        )
                    ],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[
                        ElementPropertyFilter(
                            key=Key.text,
                            value=["some text"],
                            operator=PropertyOperator.exact,
                        )
                    ],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[SessionPropertyFilter(value=1, operator=PropertyOperator.gt)],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[CohortPropertyFilter(value=2)],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[
                        GroupPropertyFilter(
                            key="name",
                            value=["Hedgebox Inc."],
                            operator=PropertyOperator.exact,
                            group_type_index=2,
                        )
                    ],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[HogQLPropertyFilter(key="dateDiff('minute', timestamp, now()) < 30")],
                ),
                EventsNode(
                    event="$pageview",
                    name="$pageview",
                    properties=[
                        EventPropertyFilter(
                            key="$referring_domain",
                            value="google",
                            operator=PropertyOperator.icontains,
                        ),
                        EventPropertyFilter(
                            key="utm_source",
                            value="is_not_set",
                            operator=PropertyOperator.is_not_set,
                        ),
                    ],
                ),
            ],
        )

    def test_breakdown(self):
        filter = {"breakdown_type": "event", "breakdown": "$browser"}

        query = filter_to_query(filter)

        self.assertEqual(
            query.breakdown,
            BreakdownFilter(breakdown_type=BreakdownType.event, breakdown="$browser"),
        )

    def test_breakdown_converts_multi(self):
        filter = {"breakdowns": [{"type": "event", "property": "$browser"}]}

        query = filter_to_query(filter)

        self.assertEqual(
            query.breakdown,
            BreakdownFilter(breakdown_type=BreakdownType.event, breakdown="$browser"),
        )

    def test_breakdown_type_default(self):
        filter = {"breakdown": "some_prop"}

        query = filter_to_query(filter)

        self.assertEqual(
            query.breakdown,
            BreakdownFilter(breakdown_type=BreakdownType.event, breakdown="some_prop"),
        )

    def test_trends_filter(self):
        filter = {
            "smoothing_intervals": 2,
            "compare": True,
            "aggregation_axis_format": "duration_ms",
            "aggregation_axis_prefix": "pre",
            "aggregation_axis_postfix": "post",
            "decimal_places": 5,
            "formula": "A + B",
            "shown_as": "Volume",
            "display": "ActionsAreaGraph",
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.trendsFilter,
            TrendsFilter(
                smoothing_intervals=2,
                compare=True,
                aggregation_axis_format=AggregationAxisFormat.duration_ms,
                aggregation_axis_prefix="pre",
                aggregation_axis_postfix="post",
                formula="A + B",
                display=ChartDisplayType.ActionsAreaGraph,
                decimal_places=5,
            ),
        )

    def test_funnels_filter(self):
        filter = {
            "insight": "FUNNELS",
            "funnel_viz_type": "steps",
            "funnel_window_interval_unit": "hour",
            "funnel_window_interval": 13,
            "breakdown_attribution_type": "step",
            "breakdown_attribution_value": 2,
            "funnel_order_type": "strict",
            "funnel_aggregate_by_hogql": "person_id",
            "exclusions": [
                {
                    "id": "$pageview",
                    "type": "events",
                    "order": 0,
                    "name": "$pageview",
                    "funnel_from_step": 1,
                    "funnel_to_step": 2,
                }
            ],
            "bin_count": 15,  # used in time to convert: number of bins to show in histogram
            "funnel_from_step": 1,  # used in time to convert: initial step index to compute time to convert
            "funnel_to_step": 2,  # used in time to convert: ending step index to compute time to convert
            #
            # frontend only params
            # "layout": layout,
            # "funnel_step_reference": "previous", # whether conversion shown in graph should be across all steps or just from the previous step
            # hidden_legend_keys # used to toggle visibilities in table and legend
            #
            # persons endpoint only params
            # "funnel_step_breakdown": funnel_step_breakdown, # used in steps breakdown: persons modal
            # "funnel_correlation_person_entity":funnel_correlation_person_entity,
            # "funnel_correlation_person_converted":funnel_correlation_person_converted, # success or failure counts
            # "entrance_period_start": entrance_period_start, # this and drop_off is used for funnels time conversion date for the persons modal
            # "drop_off": drop_off,
            # "funnel_step": funnel_step,
            # "funnel_custom_steps": funnel_custom_steps,
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.funnelsFilter,
            FunnelsFilter(
                funnel_viz_type=FunnelVizType.steps,
                funnel_from_step=1,
                funnel_to_step=2,
                funnel_window_interval_unit=FunnelConversionWindowTimeUnit.hour,
                funnel_window_interval=13,
                breakdown_attribution_type=BreakdownAttributionType.step,
                breakdown_attribution_value=2,
                funnel_order_type=StepOrderValue.strict,
                exclusions=[
                    FunnelExclusion(
                        id="$pageview",
                        type=EntityType.events,
                        order=0,
                        name="$pageview",
                        funnel_from_step=1,
                        funnel_to_step=2,
                    )
                ],
                bin_count=15,
                funnel_aggregate_by_hogql="person_id",
                # funnel_step_reference=FunnelStepReference.previous,
            ),
        )

    def test_retention_filter(self):
        filter = {
            "insight": "RETENTION",
            "retention_type": "retention_first_time",
            # retention_reference="previous",
            "total_intervals": 12,
            "returning_entity": {
                "id": "$pageview",
                "name": "$pageview",
                "type": "events",
            },
            "target_entity": {"id": "$pageview", "name": "$pageview", "type": "events"},
            "period": "Week",
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.retentionFilter,
            RetentionFilter(
                retention_type=RetentionType.retention_first_time,
                total_intervals=12,
                period=RetentionPeriod.Week,
                returning_entity={
                    "id": "$pageview",
                    "name": "$pageview",
                    "type": "events",
                    "custom_name": None,
                    "order": None,
                },
                target_entity={
                    "id": "$pageview",
                    "name": "$pageview",
                    "type": "events",
                    "custom_name": None,
                    "order": None,
                },
            ),
        )

    def test_paths_filter(self):
        filter = {
            "insight": "PATHS",
            "include_event_types": ["$pageview", "hogql"],
            "start_point": "http://localhost:8000/events",
            "end_point": "http://localhost:8000/home",
            "paths_hogql_expression": "event",
            "edge_limit": 50,
            "min_edge_weight": 10,
            "max_edge_weight": 20,
            "local_path_cleaning_filters": [{"alias": "merchant", "regex": "\\/merchant\\/\\d+\\/dashboard$"}],
            "path_replacements": True,
            "exclude_events": ["http://localhost:8000/events"],
            "step_limit": 5,
            "path_groupings": ["/merchant/*/payment"],
            "funnel_paths": "funnel_path_between_steps",
            "funnel_filter": {
                "insight": "FUNNELS",
                "events": [
                    {
                        "type": "events",
                        "id": "$pageview",
                        "order": 0,
                        "name": "$pageview",
                        "math": "total",
                    },
                    {"type": "events", "id": None, "order": 1, "math": "total"},
                ],
                "funnel_viz_type": "steps",
                "exclusions": [],
                "filter_test_accounts": True,
                "funnel_step": 2,
            },
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.pathsFilter,
            PathsFilter(
                include_event_types=[PathType.field_pageview, PathType.hogql],
                paths_hogql_expression="event",
                start_point="http://localhost:8000/events",
                end_point="http://localhost:8000/home",
                edge_limit=50,
                min_edge_weight=10,
                max_edge_weight=20,
                local_path_cleaning_filters=[
                    PathCleaningFilter(alias="merchant", regex="\\/merchant\\/\\d+\\/dashboard$")
                ],
                path_replacements=True,
                exclude_events=["http://localhost:8000/events"],
                step_limit=5,
                path_groupings=["/merchant/*/payment"],
                funnel_paths=FunnelPathType.funnel_path_between_steps,
                funnel_filter={
                    "insight": "FUNNELS",
                    "events": [
                        {
                            "type": "events",
                            "id": "$pageview",
                            "order": 0,
                            "name": "$pageview",
                            "math": "total",
                        },
                        {"type": "events", "id": None, "order": 1, "math": "total"},
                    ],
                    "funnel_viz_type": "steps",
                    "exclusions": [],
                    "filter_test_accounts": True,
                    "funnel_step": 2,
                },
            ),
        )

    def test_stickiness_filter(self):
        filter = {"insight": "STICKINESS", "compare": True, "shown_as": "Stickiness"}

        query = filter_to_query(filter)

        self.assertEqual(
            query.stickinessFilter,
            StickinessFilter(compare=True),
        )

    def test_lifecycle_filter(self):
        filter = {
            "insight": "LIFECYCLE",
            "shown_as": "Lifecycle",
        }

        query = filter_to_query(filter)

        self.assertEqual(
            query.lifecycleFilter,
            None,
        )
