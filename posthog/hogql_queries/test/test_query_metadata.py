from unittest.mock import Mock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    ActorsQuery,
    CalendarHeatmapQuery,
    DataTableNode,
    EntityType,
    EventPropertyFilter,
    EventsNode,
    EventsQuery,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationResultsType,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelsActorsQuery,
    FunnelsFilter,
    FunnelsQuery,
    InsightActorsQuery,
    InsightVizNode,
    LifecycleQuery,
    PathsFilter,
    PathsQuery,
    PathType,
    RetentionEntity,
    RetentionFilter,
    RetentionQuery,
    StickinessActorsQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql_queries.query_metadata import (
    MAX_PROPERTIES_PER_QUERY_METADATA,
    QueryEventsExtractor,
    QueryPropertiesExtractor,
    extract_query_metadata,
)

from products.actions.backend.models.action import Action


class TestQueryEventsExtractor(TestCase):
    def setUp(self):
        self.team = Mock(id=1)
        self.extractor = QueryEventsExtractor(team=self.team)

    def test_extract_events_empty_query(self):
        """Test that empty query returns empty list"""
        result = self.extractor.extract_events({})
        self.assertCountEqual(result, [])

        result = self.extractor.extract_events(None)  # type: ignore
        self.assertCountEqual(result, [])

    def test_extract_events_trends_query(self):
        """Test extracting events from TrendsQuery"""
        query = TrendsQuery(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="click"),
            ]
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "click"])

    @patch("products.actions.backend.models.action.Action.objects.get")
    def test_extract_events_with_actions_node(self, mock_action_get):
        """Test extracting events from query with ActionsNode"""
        mock_action = Mock()
        mock_action.get_step_events.return_value = ["signup", "purchase"]
        mock_action_get.return_value = mock_action

        query = TrendsQuery(
            series=[
                EventsNode(event="pageview"),
                ActionsNode(id=123),
            ]
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "signup", "purchase"])

    @patch("products.actions.backend.models.action.Action.objects.get")
    def test_extract_events_with_actions_node_with_none_steps(self, mock_action_get):
        """Test extracting events from query with ActionsNode"""
        mock_action = Mock()
        mock_action.get_step_events.return_value = ["signup", None]
        mock_action_get.return_value = mock_action

        query = TrendsQuery(
            series=[
                EventsNode(event="pageview"),
                ActionsNode(id=123),
            ]
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "signup"])

    @patch("products.actions.backend.models.action.Action.objects.get")
    def test_extract_events_with_non_existent_action(self, mock_action_get):
        """Test extracting events from query with non-existent ActionsNode"""
        mock_action_get.side_effect = Action.DoesNotExist
        query = TrendsQuery(
            series=[
                ActionsNode(id=999),  # Non-existent action ID
            ]
        )

        # The extractor should handle the missing action gracefully
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, [])

        mock_action_get.assert_called_once_with(pk=999, team__project_id=self.team.project_id)

    def test_extract_events_stickiness_query(self):
        """Test extracting events from StickinessQuery"""
        query = StickinessQuery(series=[EventsNode(event="login")])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["login"])

    def test_extract_events_lifecycle_query(self):
        """Test extracting events from LifecycleQuery"""
        query = LifecycleQuery(series=[EventsNode(event="signup")])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["signup"])

    def test_extract_events_calendar_heatmap_query(self):
        """Test extracting events from CalendarHeatmapQuery"""
        query = CalendarHeatmapQuery(series=[EventsNode(event="daily_active")])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["daily_active"])

    def test_extract_events_events_query(self):
        """Test extracting events from EventsQuery"""
        query = EventsQuery(event="pageview", select=["*"])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview"])

    def test_extract_events_events_query_no_event(self):
        """Test extracting events from EventsQuery without event specified"""
        query = EventsQuery(select=["*"])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, [])

    def test_extract_events_events_query_with_source(self):
        """Test extracting events from EventsQuery with source"""
        query = EventsQuery(
            event="click",
            source=InsightActorsQuery(
                source=TrendsQuery(series=[EventsNode(event="signup"), EventsNode(event="purchase")])
            ),
            select=["*"],
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["click", "signup", "purchase"])

    def test_extract_events_events_query_with_source_none(self):
        """Test extracting events from EventsQuery with source as None"""
        query = EventsQuery(event="click", source=None, select=["*"])
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["click"])

    def test_extract_events_funnels_query(self):
        """Test extracting events from FunnelsQuery"""
        query = FunnelsQuery(
            series=[
                EventsNode(event="signup"),
                EventsNode(event="purchase"),
            ],
            funnelsFilter=FunnelsFilter(
                exclusions=[
                    FunnelExclusionEventsNode(
                        event="abandon_cart",
                        funnelFromStep=0,
                        funnelToStep=1,
                    ),
                    FunnelExclusionEventsNode(
                        event="logout",
                        funnelFromStep=1,
                        funnelToStep=2,
                    ),
                ]
            ),
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["signup", "purchase", "abandon_cart", "logout"])

    @patch("products.actions.backend.models.action.Action.objects.get")
    def test_extract_events_funnels_query_exclusions_actions(self, mock_action_get):
        """Test extracting events from FunnelsQuery with exclusions that include actions"""
        mock_action = Mock()
        mock_action.get_step_events.return_value = ["action_event_1", "action_event_2"]
        mock_action_get.return_value = mock_action

        query = FunnelsQuery(
            series=[
                EventsNode(event="signup"),
                EventsNode(event="purchase"),
            ],
            funnelsFilter=FunnelsFilter(
                exclusions=[
                    FunnelExclusionEventsNode(
                        event="abandon_cart",
                        funnelFromStep=0,
                        funnelToStep=1,
                    ),
                    FunnelExclusionActionsNode(
                        id=123,
                        name="Some action",
                        funnelFromStep=1,
                        funnelToStep=2,
                    ),
                ]
            ),
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["signup", "purchase", "abandon_cart", "action_event_1", "action_event_2"])

    def test_extract_events_funnels_query_no_funnels_filter(self):
        """Test extracting events from FunnelsQuery without funnelsFilter"""
        query = FunnelsQuery(
            series=[
                EventsNode(event="signup"),
                EventsNode(event="purchase"),
            ],
            funnelsFilter=None,
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["signup", "purchase"])

    @patch("products.actions.backend.models.action.Action.objects.get")
    def test_extract_events_retention_query(self, mock_action_get):
        """Test extracting events from RetentionQuery"""
        mock_action = Mock()
        mock_action.get_step_events.return_value = ["signup"]
        mock_action_get.return_value = mock_action

        query = RetentionQuery(
            retentionFilter=RetentionFilter(
                targetEntity=RetentionEntity(type=EntityType.EVENTS, id="pageview"),
                returningEntity=RetentionEntity(type=EntityType.ACTIONS, id="123"),
            )
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "signup"])

    def test_extract_events_paths_query(self):
        """Test extracting events from PathsQuery"""
        query = PathsQuery(
            pathsFilter=PathsFilter(
                includeEventTypes=[PathType.FIELD_PAGEVIEW, PathType.FIELD_SCREEN],
                excludeEvents=["logout", "https://example.com"],  # URL should be filtered out
            )
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, [str(PathType.FIELD_PAGEVIEW), str(PathType.FIELD_SCREEN), "logout"])

    def test_extract_events_insight_viz_node(self):
        """Test extracting events from InsightVizNode"""
        source_query = TrendsQuery(series=[EventsNode(event="pageview")])
        query = InsightVizNode(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview"])

    def test_extract_events_data_table_node(self):
        """Test extracting events from DataTableNode"""
        source_query = EventsQuery(select=["*"], event="click")
        query = DataTableNode(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["click"])

    def test_extract_events_event_node(self):
        """Test extracting events from DataTableNode"""
        query = EventsNode(event="click")
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["click"])

    def test_extract_events_actors_query(self):
        """Test extracting events from ActorsQuery"""
        source_query = InsightActorsQuery(source=TrendsQuery(series=[EventsNode(event="user_action")]))
        query = ActorsQuery(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["user_action"])

    def test_extract_events_actors_query_no_source(self):
        """Test extracting events from ActorsQuery with no source"""
        query = ActorsQuery(source=None)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, [])

    def test_extract_events_insight_actors_query(self):
        """Test extracting events from InsightActorsQuery"""
        source_query = FunnelsQuery(series=[EventsNode(event="step1")], funnelsFilter=FunnelsFilter(exclusions=[]))
        query = InsightActorsQuery(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["step1"])

    def test_extract_events_funnels_actors_query(self):
        """Test extracting events from FunnelsActorsQuery"""
        source_query = FunnelsQuery(
            series=[EventsNode(event="funnel_step")], funnelsFilter=FunnelsFilter(exclusions=[])
        )
        query = FunnelsActorsQuery(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["funnel_step"])

    def test_extract_events_funnel_correlation_actors_query(self):
        """Test extracting events from FunnelCorrelationActorsQuery"""

        funnels_query = FunnelsQuery(
            series=[EventsNode(event="funnel_event")], funnelsFilter=FunnelsFilter(exclusions=[])
        )
        actors_query = FunnelsActorsQuery(source=funnels_query)
        source_query = FunnelCorrelationQuery(
            source=actors_query,
            funnelCorrelationExcludeEventNames=["exclude_event"],
            funnelCorrelationEventNames=["correlation_event"],
            funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
        )
        query = FunnelCorrelationActorsQuery(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["funnel_event", "correlation_event", "exclude_event"])

    def test_extract_events_stickiness_actors_query(self):
        """Test extracting events from StickinessActorsQuery"""
        source_query = StickinessQuery(series=[EventsNode(event="sticky_event")])
        query = StickinessActorsQuery(source=source_query)
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["sticky_event"])

    def test_extract_events_funnel_correlation_query(self):
        """Test extracting events from FunnelCorrelationQuery"""
        funnels_query = FunnelsQuery(
            series=[EventsNode(event="funnel_event")], funnelsFilter=FunnelsFilter(exclusions=[])
        )
        actors_query = FunnelsActorsQuery(source=funnels_query)
        source_query = FunnelCorrelationQuery(
            source=actors_query,
            funnelCorrelationExcludeEventNames=["exclude_event"],
            funnelCorrelationEventNames=["correlation_event"],
            funnelCorrelationType=FunnelCorrelationResultsType.EVENTS,
        )
        result = self.extractor.extract_events(source_query)
        self.assertCountEqual(result, ["funnel_event", "correlation_event", "exclude_event"])

    def test_extract_events_from_dict(self):
        """Test extracting events from dictionary input"""
        query_dict = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "pageview"}, {"kind": "EventsNode", "event": "click"}],
        }
        result = self.extractor.extract_events(query_dict)
        self.assertCountEqual(result, ["pageview", "click"])

    def test_extract_events_deduplication(self):
        """Test that duplicate events are removed"""
        query = TrendsQuery(
            series=[
                EventsNode(event="pageview"),
                EventsNode(event="pageview"),
                EventsNode(event="click"),
            ]
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "click"])

    def test_extract_events_hogql_query(self):
        query = {
            "kind": "DataTableNode",
            "source": {
                "kind": "HogQLQuery",
                "query": "select count() from events where event = '$pageview' or event in ('signup', 'purchase')",
            },
        }
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["$pageview", "signup", "purchase"])

    def test_extract_events_invalid_hogql_query(self):
        result = self.extractor.extract_events({"kind": "HogQLQuery", "query": "select ((( from"})
        self.assertCountEqual(result, [])


class TestQueryPropertiesExtractor(TestCase):
    def setUp(self):
        self.extractor = QueryPropertiesExtractor()

    @parameterized.expand(
        [
            (
                "series_and_global_property_filters",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "pageview",
                            "properties": [{"key": "$browser", "type": "event", "value": "Chrome"}],
                        }
                    ],
                    "properties": [{"key": "email", "type": "person", "value": "test"}],
                },
                [("event", "$browser"), ("person", "email")],
            ),
            (
                "feature_filter_maps_to_event_definition",
                {"kind": "TrendsQuery", "properties": [{"key": "$feature/foo", "type": "feature", "value": "test"}]},
                [("event", "$feature/foo")],
            ),
            (
                "group_and_session_filters",
                {
                    "kind": "TrendsQuery",
                    "properties": [
                        {"key": "industry", "type": "group", "group_type_index": 0, "value": "tech"},
                        {"key": "$session_duration", "type": "session", "value": 60},
                    ],
                },
                [("group", "industry"), ("session", "$session_duration")],
            ),
            (
                "unattributable_filter_types_skipped",
                {
                    "kind": "TrendsQuery",
                    "properties": [
                        {"key": "id", "type": "cohort", "value": 5},
                        {"key": "properties.x > 1", "type": "hogql"},
                        {"key": "column", "type": "data_warehouse", "value": "a"},
                    ],
                },
                [],
            ),
            (
                "breakdown_defaults_to_event",
                {"kind": "TrendsQuery", "breakdownFilter": {"breakdown": "$browser"}},
                [("event", "$browser")],
            ),
            (
                "breakdown_with_type",
                {
                    "kind": "TrendsQuery",
                    "breakdownFilter": {"breakdown": "$geoip_country_code", "breakdown_type": "person"},
                },
                [("person", "$geoip_country_code")],
            ),
            (
                "cohort_breakdown_skipped",
                {"kind": "TrendsQuery", "breakdownFilter": {"breakdown": [11, 12], "breakdown_type": "cohort"}},
                [],
            ),
            (
                "multiple_breakdowns",
                {
                    "kind": "TrendsQuery",
                    "breakdownFilter": {
                        "breakdowns": [
                            {"property": "$browser", "type": "event"},
                            {"property": "email", "type": "person"},
                        ]
                    },
                },
                [("event", "$browser"), ("person", "email")],
            ),
            (
                "math_property_defaults_to_event",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "purchase", "math": "sum", "math_property": "revenue"}],
                },
                [("event", "revenue")],
            ),
            (
                "math_property_session_type",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "event": "purchase",
                            "math": "avg",
                            "math_property": "$session_duration",
                            "math_property_type": "session_properties",
                        }
                    ],
                },
                [("session", "$session_duration")],
            ),
            (
                "deduplicates_repeated_references",
                {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "EventsNode", "event": "a", "properties": [{"key": "$browser", "type": "event"}]},
                        {"kind": "EventsNode", "event": "b", "properties": [{"key": "$browser", "type": "event"}]},
                    ],
                },
                [("event", "$browser")],
            ),
            (
                "hogql_query_properties",
                {
                    "kind": "DataTableNode",
                    "source": {
                        "kind": "HogQLQuery",
                        "query": "select properties.$browser, properties['$os'] from events",
                    },
                },
                [("event", "$browser"), ("event", "$os")],
            ),
            (
                "invalid_hogql_contributes_nothing",
                {"kind": "HogQLQuery", "query": "select ((( from"},
                [],
            ),
        ]
    )
    def test_extract_properties(self, _name, query, expected):
        result = self.extractor.extract_properties(query)
        self.assertCountEqual([(prop.type, prop.name) for prop in result], expected)

    def test_extract_properties_from_pydantic_query(self):
        query = TrendsQuery(series=[EventsNode(event="pageview", properties=[EventPropertyFilter(key="$browser")])])
        result = self.extractor.extract_properties(query)
        self.assertCountEqual([(prop.type, prop.name) for prop in result], [("event", "$browser")])

    def test_extract_properties_caps_reference_count(self):
        query = {
            "kind": "TrendsQuery",
            "properties": [{"key": f"prop_{i}", "type": "event"} for i in range(150)],
        }
        result = self.extractor.extract_properties(query)
        self.assertEqual(len(result), MAX_PROPERTIES_PER_QUERY_METADATA)


class TestExtractQueryMetadata(TestCase):
    def test_includes_events_and_properties(self):
        metadata = extract_query_metadata(
            {
                "kind": "TrendsQuery",
                "series": [
                    {
                        "kind": "EventsNode",
                        "event": "pageview",
                        "properties": [{"key": "$browser", "type": "event", "value": "Chrome"}],
                    }
                ],
            },
            Mock(id=1),
        )
        self.assertEqual(metadata.events, ["pageview"])
        self.assertEqual([(prop.type, prop.name) for prop in metadata.properties], [("event", "$browser")])

    def test_empty_query_has_empty_properties(self):
        metadata = extract_query_metadata(None, Mock(id=1))
        self.assertEqual(metadata.events, [])
        self.assertEqual(metadata.properties, [])
