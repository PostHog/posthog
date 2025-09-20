import uuid
from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import (
    CachedEventsQueryResponse,
    CachedSessionBatchEventsQueryResponse,
    EventsQuery,
    SessionBatchEventsQuery,
    SessionBatchEventsQueryResponse,
)

from posthog.hogql_queries.ai.session_batch_events_query_runner import (
    SessionBatchEventsQueryRunner,
    create_session_batch_events_query,
)
from posthog.hogql_queries.events_query_runner import EventsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner


class TestSessionBatchEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    @pytest.fixture(autouse=True)
    def setup_session_ids(self):
        """Setup proper UUID session IDs for tests."""
        self.session_1_id = str(uuid.uuid4())
        self.session_2_id = str(uuid.uuid4())
        self.session_3_id = str(uuid.uuid4())
        self.session_4_id = str(uuid.uuid4())

    def _create_events_for_sessions(self, data: list[tuple[str, str, str, Any]]):
        """Create events for testing with session IDs."""

        for distinct_id, timestamp, session_id, event_properties in data:
            with freeze_time(timestamp):
                # Add session_id to event properties
                properties = {**event_properties, "$session_id": session_id}
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties=properties,
                )
        flush_persons_and_events()

    def test_simple_events_query(self):
        # Create sample events
        self._create_events_for_sessions(
            [
                # Session 1 events
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
                # Session 2 events
                ("user2", "2025-01-11T13:00:01Z", self.session_2_id, {"page": "/home"}),
                # Session 3 events
                ("user3", "2025-01-11T14:00:01Z", self.session_3_id, {"page": "/login"}),
            ]
        )
        # Query to get all
        with freeze_time("2025-01-11T16:00:00"):
            query = EventsQuery(
                kind="EventsQuery",
                select=["*"],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                orderBy=["timestamp ASC"],
            )
            runner = EventsQueryRunner(query=query, team=self.team)
            response = runner.run()
        # Verify results
        assert isinstance(response, CachedEventsQueryResponse)
        assert len(response.results) == 3
        assert response.results[0][0]["distinct_id"] == "user1"
        assert response.results[1][0]["distinct_id"] == "user2"
        assert response.results[2][0]["distinct_id"] == "user3"

    def test_basic_session_batch_query(self):
        """Test happy path for session batch query"""
        self._create_events_for_sessions(  # Create events for three different sessions
            [
                # Session 1 events
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
                ("user1", "2025-01-11T12:01:00Z", self.session_1_id, {"page": "/about"}),
                ("user1", "2025-01-11T12:02:00Z", self.session_1_id, {"page": "/contact"}),
                # Session 2 events
                ("user2", "2025-01-11T13:00:01Z", self.session_2_id, {"page": "/home"}),
                ("user2", "2025-01-11T13:01:00Z", self.session_2_id, {"page": "/products"}),
                # Session 3 events
                ("user3", "2025-01-11T14:00:01Z", self.session_3_id, {"page": "/login"}),
                # Session not in our query (should be ignored)
                ("user4", "2025-01-11T15:00:01Z", self.session_4_id, {"page": "/signup"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            # Create query for sessions 1, 2, and 3 (excluding session_4)
            query = create_session_batch_events_query(
                session_ids=[self.session_1_id, self.session_2_id, self.session_3_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()

            # Validate the response
            self.assertIsInstance(response, SessionBatchEventsQueryResponse)
            # Should have session_events populated since group_by_session=True by default
            self.assertIsNotNone(response.session_events)
            assert response.session_events is not None
            # Should have 3 sessions in results
            self.assertEqual(len(response.session_events), 3)
            # Verify no sessions had missing events
            self.assertEqual(response.sessions_with_no_events, [])

            # Check each session's events
            session_events_by_id = {item.session_id: item for item in response.session_events}
            # Session 1 should have 3 events
            self.assertIn(self.session_1_id, session_events_by_id)
            session_1 = session_events_by_id[self.session_1_id]
            self.assertEqual(len(session_1.events), 3)
            # Session 2 should have 2 events
            self.assertIn(self.session_2_id, session_events_by_id)
            session_2 = session_events_by_id[self.session_2_id]
            self.assertEqual(len(session_2.events), 2)
            # Session 3 should have 1 event
            self.assertIn(self.session_3_id, session_events_by_id)
            session_3 = session_events_by_id[self.session_3_id]
            self.assertEqual(len(session_3.events), 1)
            # Verify all required columns are present
            self.assertIsNotNone(response.columns)
            expected_columns = ["event", "timestamp", "properties.page"]  # $session_id removed during grouping
            self.assertEqual(response.columns, expected_columns)

    def test_session_with_no_events(self):
        """Test handling of sessions that have no matching events."""
        self._create_events_for_sessions(  # Create events for only one session
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            # Query for multiple sessions, but only one has events
            query = create_session_batch_events_query(
                session_ids=[self.session_1_id, self.session_2_id, self.session_3_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()
            # Should have 1 session with events
            assert response.session_events is not None
            self.assertEqual(len(response.session_events), 1)
            # Should track sessions with no events
            assert response.sessions_with_no_events is not None
            self.assertEqual(set(response.sessions_with_no_events), {self.session_2_id, self.session_3_id})
            # The one session with events should be session_1
            self.assertEqual(response.session_events[0].session_id, self.session_1_id)

    def test_events_to_ignore_filter(self):
        """Test that events_to_ignore parameter properly filters out unwanted events."""
        self._create_events_for_sessions(  # Create a default pageview event
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ]
        )
        # Create a feature flag event that should be ignored by default
        with freeze_time("2025-01-11T12:01:00Z"):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id="user1",
                timestamp="2025-01-11T12:01:00Z",
                properties={"$session_id": self.session_1_id, "flag": "test_flag"},
            )
        flush_persons_and_events()
        # Query the events with and without ignoring the feature flag event
        with freeze_time("2025-01-11T16:00:00"):
            for ignore_status in [True, False]:
                if ignore_status:
                    # Use default ignore settings
                    events_to_ignore: list[str] | None = None
                else:
                    # Don't ignore any events
                    events_to_ignore = []
                query = create_session_batch_events_query(
                    session_ids=[self.session_1_id],
                    after="2025-01-10T00:00:00",
                    before="2025-01-12T00:00:00",
                    select=["event", "timestamp", "properties.page", "properties.$session_id"],
                    events_to_ignore=events_to_ignore,
                )
                runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
                response = runner.calculate()
                # Verify if the events were ignored of not
                if ignore_status:
                    # Should have only 1 event (the $pageview), not the feature flag event
                    assert response.session_events is not None
                    session_1 = response.session_events[0]
                    event_name_1 = session_1.events[0][0]
                    self.assertEqual(event_name_1, "$pageview")
                else:
                    # Should have 2 events (the $pageview and the feature flag event)
                    assert response.session_events is not None
                    session_1 = response.session_events[0]
                    event_name_1 = session_1.events[0][0]
                    self.assertEqual(event_name_1, "$pageview")
                    event_name_2 = session_1.events[1][0]
                    self.assertEqual(event_name_2, "$feature_flag_called")

    def test_group_by_session_false(self):
        """Test that group_by_session=False returns ungrouped results."""
        self._create_events_for_sessions(
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
                ("user2", "2025-01-11T13:00:01Z", self.session_2_id, {"page": "/about"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            # Create query with group_by_session=False
            query = SessionBatchEventsQuery(
                session_ids=[self.session_1_id, self.session_2_id],
                select=["event", "timestamp", "properties.$session_id"],
                where=[f"properties.$session_id IN ['{self.session_1_id}', '{self.session_2_id}']"],
                after="-24h",
                group_by_session=False,  # This should return ungrouped results
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()
            # Should not have session_events populated
            self.assertIsNone(response.session_events)
            # Should have regular results instead
            self.assertIsNotNone(response.results)
            self.assertEqual(len(response.results), 2)  # 2 total events

    def test_custom_field_selection(self):
        """Test custom field selection in session batch queries."""
        self._create_events_for_sessions(
            [
                (
                    "user1",
                    "2025-01-11T12:00:01Z",
                    self.session_1_id,
                    {"page": "/home", "user_agent": "Chrome", "custom_field": "test_value"},
                ),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            # Query with custom field selection
            query = create_session_batch_events_query(
                session_ids=[self.session_1_id],
                select=["event", "properties.page", "properties.custom_field"],
                after="2025-01-10T00:00:00",
                before="2025-01-12T00:00:00",
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()
            # Verify custom columns are returned
            expected_columns = ["event", "properties.page", "properties.custom_field"]
            self.assertEqual(response.columns, expected_columns)
            # Verify event data matches selected fields
            assert response.session_events is not None
            session_1 = response.session_events[0]
            event_row = session_1.events[0]
            self.assertEqual(event_row[0], "$pageview")  # event
            self.assertEqual(event_row[1], "/home")  # properties.page
            self.assertEqual(event_row[2], "test_value")  # properties.custom_field

    def test_cached_response_type(self):
        """Test that the runner returns cached response when run"""
        self._create_events_for_sessions(
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            query = create_session_batch_events_query(
                session_ids=[self.session_1_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            # Validate response
            assert isinstance(response, CachedSessionBatchEventsQueryResponse)
            # Should have all the caching fields
            self.assertIsNotNone(response.cache_key)
            self.assertIsNotNone(response.is_cached)
            self.assertIsNotNone(response.last_refresh)
            self.assertIsNotNone(response.next_allowed_client_refresh)
            self.assertIsNotNone(response.timezone)
            # Should also have the session-specific fields
            self.assertIsNotNone(response.session_events)
            assert response.session_events is not None
            self.assertEqual(len(response.session_events), 1)
            self.assertEqual(response.session_events[0].session_id, self.session_1_id)
            self.assertEqual(response.sessions_with_no_events, [])
            # Should have the standard response fields
            self.assertIsNotNone(response.columns)
            self.assertIsNotNone(response.results)
            self.assertIsNotNone(response.hogql)

    def test_cached_response_vs_calculate(self):
        """Test that cached response includes the same session data as calculate()."""
        self._create_events_for_sessions(
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
                ("user2", "2025-01-11T13:00:01Z", self.session_2_id, {"page": "/about"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            query = create_session_batch_events_query(
                session_ids=[self.session_1_id, self.session_2_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            # Get both responses
            calculate_response = runner.calculate()
            cached_response = runner.run()
            # Verify both are the correct types
            assert isinstance(calculate_response, SessionBatchEventsQueryResponse)
            assert isinstance(cached_response, CachedSessionBatchEventsQueryResponse)
            # Session-specific data should be identical
            assert calculate_response.session_events is not None
            assert cached_response.session_events is not None
            self.assertEqual(len(calculate_response.session_events), len(cached_response.session_events))
            self.assertEqual(calculate_response.sessions_with_no_events, cached_response.sessions_with_no_events)
            # Core data should be identical
            self.assertEqual(calculate_response.results, cached_response.results)
            self.assertEqual(calculate_response.columns, cached_response.columns)
            self.assertEqual(calculate_response.hogql, cached_response.hogql)

    def test_cached_response_ungrouped(self):
        """Test cached response when group_by_session=False."""
        self._create_events_for_sessions(
            [
                ("user1", "2025-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            query = SessionBatchEventsQuery(
                session_ids=[self.session_1_id],
                select=["event", "timestamp", "properties.$session_id"],
                where=[f"properties.$session_id IN ['{self.session_1_id}']"],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                group_by_session=False,  # Should not group by session
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.run()
            # Should be cached response
            assert isinstance(response, CachedSessionBatchEventsQueryResponse)
            # Should not have session_events populated
            self.assertIsNone(response.session_events)
            # Should have regular results
            self.assertIsNotNone(response.results)
            self.assertEqual(len(response.results), 1)

    def test_pagination_with_offset(self):
        """Test pagination functionality with offset parameter using HogQLHasMorePaginator."""
        session_id = self.session_1_id
        self._create_events_for_sessions(  # Create 5 events for a single session
            [
                ("user1", "2025-01-11T12:00:01Z", session_id, {"page": "/page1"}),
                ("user1", "2025-01-11T12:01:00Z", session_id, {"page": "/page2"}),
                ("user1", "2025-01-11T12:02:00Z", session_id, {"page": "/page3"}),
                ("user1", "2025-01-11T12:03:00Z", session_id, {"page": "/page4"}),
                ("user1", "2025-01-11T12:04:00Z", session_id, {"page": "/page5"}),
            ]
        )
        with freeze_time("2025-01-11T16:00:00"):
            all_events = []
            # Test first page with limit=2, offset=0
            query = create_session_batch_events_query(
                session_ids=[session_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
                max_total_events=2,
                offset=0,
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.run()

            # Verify first page response
            assert isinstance(response, CachedSessionBatchEventsQueryResponse)
            self.assertIsNotNone(response.session_events)
            assert response.session_events is not None
            self.assertEqual(len(response.session_events), 1)  # One session with 2 events
            session_events = response.session_events[0]
            self.assertEqual(session_events.session_id, session_id)
            self.assertEqual(len(session_events.events), 2)
            # Should have hasMore=True since there are more events
            self.assertTrue(response.hasMore)
            self.assertEqual(response.limit, 2)
            self.assertEqual(response.offset, 0)
            all_events.extend(session_events.events)

            # Test second page with limit=2, offset=2
            query = create_session_batch_events_query(
                session_ids=[session_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
                max_total_events=2,
                offset=2,
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.run()

            # Verify second page response
            assert isinstance(response, CachedSessionBatchEventsQueryResponse)
            self.assertIsNotNone(response.session_events)
            assert response.session_events is not None
            self.assertEqual(len(response.session_events), 1)
            session_events = response.session_events[0]
            self.assertEqual(session_events.session_id, session_id)
            self.assertEqual(len(session_events.events), 2)
            # Should have hasMore=True since there's still one more event
            self.assertTrue(response.hasMore)
            self.assertEqual(response.limit, 2)
            self.assertEqual(response.offset, 2)
            all_events.extend(session_events.events)

            # Test third page with limit=2, offset=4
            query = create_session_batch_events_query(
                session_ids=[session_id],
                before="2025-01-12T00:00:00",
                after="2025-01-10T00:00:00",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
                max_total_events=2,
                offset=4,
            )
            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.run()

            # Verify third page response
            assert isinstance(response, CachedSessionBatchEventsQueryResponse)
            self.assertIsNotNone(response.session_events)
            assert response.session_events is not None
            self.assertEqual(len(response.session_events), 1)
            session_events = response.session_events[0]
            self.assertEqual(session_events.session_id, session_id)
            self.assertEqual(len(session_events.events), 1)  # Only 1 event left
            # Should have hasMore=False since no more events
            self.assertFalse(response.hasMore)
            self.assertEqual(response.limit, 2)
            self.assertEqual(response.offset, 4)
            all_events.extend(session_events.events)

            # Verify we collected all 5 events across the 3 iterations
            self.assertEqual(len(all_events), 5)
            # Verify the events are in chronological order and contain expected pages
            expected_pages = ["/page1", "/page2", "/page3", "/page4", "/page5"]
            actual_pages = [event[2] for event in all_events]  # properties.page is at index 2
            self.assertEqual(actual_pages, expected_pages)

    def test_get_session_batch_query_runner(self):
        """Test that get_query_runner correctly returns session batch runner."""
        query = create_session_batch_events_query(
            session_ids=[self.session_1_id],
            select=["event", "timestamp"],
            max_total_events=10,
        )
        # Get the runner via get_query_runner
        runner = get_query_runner(query=query, team=self.team)
        # Verify it returns the correct runner
        assert isinstance(runner, SessionBatchEventsQueryRunner)
        self.assertEqual(runner.query.kind, "SessionBatchEventsQuery")
        self.assertEqual(runner.query.session_ids, [self.session_1_id])
        self.assertEqual(runner.query.limit, 10)
        self.assertEqual(runner.team, self.team)
