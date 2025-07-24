from unittest.mock import patch, Mock

from django.test import TestCase

from posthog.schema import (
    TrendsQuery,
    InsightVizNode,
    EventsNode,
    ActionsNode,
    FunnelsQuery,
    RetentionQuery,
    EntityType,
    RetentionEntity,
    PathsQuery,
    PathType,
    StickinessQuery,
    LifecycleQuery,
    CalendarHeatmapQuery,
    DataTableNode,
    ActorsQuery,
    InsightActorsQuery,
    FunnelsActorsQuery,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    EventsQuery,
    PathsFilter,
    RetentionFilter,
    FunnelsFilter,
    FunnelExclusionEventsNode,
    FunnelCorrelationResultsType,
)
from posthog.hogql_queries.query_metadata import QueryEventsExtractor


class TestQueryEventsExtractor(TestCase):
    def setUp(self):
        self.team = Mock(id=1)
        self.extractor = QueryEventsExtractor(team=self.team)

    def test_extract_events_empty_query(self):
        """Test that empty query returns empty list"""
        result = self.extractor.extract_events({})
        self.assertCountEqual(result, [])

        result = self.extractor.extract_events(None)
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

    @patch("posthog.hogql_queries.query_metadata.QueryEventsExtractor._get_action_events")
    def test_extract_events_with_actions_node(self, mock_get_action_events):
        """Test extracting events from query with ActionsNode"""
        mock_get_action_events.return_value = ["signup", "purchase"]

        query = TrendsQuery(
            series=[
                EventsNode(event="pageview"),
                ActionsNode(id=123),
            ]
        )
        result = self.extractor.extract_events(query)
        self.assertCountEqual(result, ["pageview", "signup", "purchase"])

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

    @patch("posthog.hogql_queries.query_metadata.QueryEventsExtractor._get_action_events")
    def test_extract_events_retention_query(self, mock_get_action_events):
        """Test extracting events from RetentionQuery"""
        mock_get_action_events.return_value = ["signup"]

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

    # def test_extract_events_stickiness_actors_query(self):
    #     """Test extracting events from StickinessActorsQuery"""
    #     source_query = StickinessQuery(
    #         series=[EventsNode(event="sticky_event")]
    #     )
    #     query = StickinessActorsQuery(source=source_query)
    #     result = self.extractor.extract_events(query)
    #     self.assertCountEqual(result, ["sticky_event"])

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
