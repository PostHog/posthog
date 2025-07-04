from typing import Any
import uuid
import pytest

from freezegun import freeze_time

from posthog.hogql_queries.ai.session_events_query_runner.runner import SessionBatchEventsQueryRunner
from posthog.hogql_queries.ai.session_events_query_runner.schema import (
    SessionBatchEventsQuery,
    SessionBatchEventsQueryResponse,
    create_session_batch_query,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
)


class TestSessionBatchEventsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    @pytest.fixture(autouse=True)
    def setup_session_ids(self):
        """Setup proper UUID session IDs for tests."""
        self.session_1_id = str(uuid.uuid4())
        self.session_2_id = str(uuid.uuid4())
        self.session_3_id = str(uuid.uuid4())
        self.session_4_id = str(uuid.uuid4())

    def _create_events_for_sessions(self, data: list[tuple[str, str, str, Any]]):
        """
        Create events for testing with session IDs.
        
        Args:
            data: List of tuples (distinct_id, timestamp, session_id, event_properties)
        """
        person_result = []
        distinct_ids_handled = set()
        
        for distinct_id, timestamp, session_id, event_properties in data:
            with freeze_time(timestamp):
                if distinct_id not in distinct_ids_handled:
                    person_result.append(
                        _create_person(
                            team_id=self.team.pk,
                            distinct_ids=[distinct_id],
                            properties={
                                "name": distinct_id,
                            },
                        )
                    )
                    distinct_ids_handled.add(distinct_id)
                
                # Add session_id to event properties
                properties = {**event_properties, "$session_id": session_id}
                
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties=properties,
                )
        
        return person_result

    def test_basic_session_batch_query(self):
        """Test basic functionality of SessionBatchEventsQueryRunner with multiple sessions."""
        # Create events for three different sessions
        self._create_events_for_sessions([
            # Session 1 events
            ("user1", "2020-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ("user1", "2020-01-11T12:01:00Z", self.session_1_id, {"page": "/about"}),
            ("user1", "2020-01-11T12:02:00Z", self.session_1_id, {"page": "/contact"}),
            
            # Session 2 events  
            ("user2", "2020-01-11T13:00:01Z", self.session_2_id, {"page": "/home"}),
            ("user2", "2020-01-11T13:01:00Z", self.session_2_id, {"page": "/products"}),
            
            # Session 3 events
            ("user3", "2020-01-11T14:00:01Z", self.session_3_id, {"page": "/login"}),
            
            # Session not in our query (should be ignored)
            ("user4", "2020-01-11T15:00:01Z", self.session_4_id, {"page": "/signup"}),
        ])
        
        flush_persons_and_events()

        with freeze_time("2020-01-11T16:00:00"):
            # Create query for sessions 1, 2, and 3 (excluding session_4)
            query = create_session_batch_query(
                session_ids=[self.session_1_id, self.session_2_id, self.session_3_id],
                after="-24h",
                select=["event", "timestamp", "properties.page", "properties.$session_id"],
            )

            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()

            # Validate response type
            self.assertIsInstance(response, SessionBatchEventsQueryResponse)
            
            # Should have session_events populated since group_by_session=True by default
            self.assertIsNotNone(response.session_events)
            
            # Should have 3 sessions in results
            self.assertEqual(response.total_sessions, 3)
            self.assertEqual(len(response.session_events), 3)
            
            # Verify no sessions had missing events
            self.assertEqual(response.sessions_with_no_events, [])
            
            # Check each session's events
            session_events_by_id = {item.session_id: item for item in response.session_events}
            
            # Session 1 should have 3 events
            self.assertIn(self.session_1_id, session_events_by_id)
            session_1 = session_events_by_id[self.session_1_id]
            self.assertEqual(session_1.event_count, 3)
            self.assertEqual(len(session_1.events), 3)
            
            # Session 2 should have 2 events
            self.assertIn(self.session_2_id, session_events_by_id)
            session_2 = session_events_by_id[self.session_2_id]
            self.assertEqual(session_2.event_count, 2)
            self.assertEqual(len(session_2.events), 2)
            
            # Session 3 should have 1 event
            self.assertIn(self.session_3_id, session_events_by_id)
            session_3 = session_events_by_id[self.session_3_id]
            self.assertEqual(session_3.event_count, 1)
            self.assertEqual(len(session_3.events), 1)
            
            # Verify columns are present
            self.assertIsNotNone(response.columns)
            expected_columns = ["event", "timestamp", "properties.page"]  # $session_id removed during grouping
            self.assertEqual(response.columns, expected_columns)

    def test_session_with_no_events(self):
        """Test handling of sessions that have no matching events."""
        # Create events for only one session
        self._create_events_for_sessions([
            ("user1", "2020-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
        ])
        
        flush_persons_and_events()

        with freeze_time("2020-01-11T16:00:00"):
            # Query for multiple sessions, but only one has events
            query = create_session_batch_query(
                session_ids=[self.session_1_id, self.session_2_id, self.session_3_id],
                after="-24h",
            )

            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()

            # Should have 1 session with events
            self.assertEqual(response.total_sessions, 1)
            self.assertEqual(len(response.session_events), 1)
            
            # Should track sessions with no events
            self.assertEqual(set(response.sessions_with_no_events), {self.session_2_id, self.session_3_id})
            
            # The one session with events should be session_1
            self.assertEqual(response.session_events[0].session_id, self.session_1_id)
            self.assertEqual(response.session_events[0].event_count, 1)

    def test_events_to_ignore_filter(self):
        """Test that events_to_ignore parameter properly filters out unwanted events."""
        # Create various types of events
        self._create_events_for_sessions([
            ("user1", "2020-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),  # $pageview
        ])
        
        # Create a feature flag event that should be ignored by default
        with freeze_time("2020-01-11T12:01:00Z"):
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id="user1",
                timestamp="2020-01-11T12:01:00Z",
                properties={"$session_id": self.session_1_id, "flag": "test_flag"},
            )
        
        flush_persons_and_events()

        with freeze_time("2020-01-11T16:00:00"):
            # Query with default events_to_ignore (should exclude $feature_flag_called)
            query = create_session_batch_query(
                session_ids=[self.session_1_id],
                after="-24h",
            )

            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()

            # Should have only 1 event (the $pageview), not the feature flag event
            self.assertEqual(response.total_sessions, 1)
            session_1 = response.session_events[0]
            self.assertEqual(session_1.event_count, 1)
            
            # Verify it's the pageview event, not the feature flag
            event_name = session_1.events[0][0]  # First column is event name
            self.assertEqual(event_name, "$pageview")

    def test_group_by_session_false(self):
        """Test that group_by_session=False returns ungrouped results."""
        self._create_events_for_sessions([
            ("user1", "2020-01-11T12:00:01Z", self.session_1_id, {"page": "/home"}),
            ("user2", "2020-01-11T13:00:01Z", self.session_2_id, {"page": "/about"}),
        ])
        
        flush_persons_and_events()

        with freeze_time("2020-01-11T16:00:00"):
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
            self.assertIsNone(response.total_sessions)
            
            # Should have regular results instead
            self.assertIsNotNone(response.results)
            self.assertEqual(len(response.results), 2)  # 2 total events

    def test_custom_field_selection(self):
        """Test custom field selection in session batch queries."""
        self._create_events_for_sessions([
            ("user1", "2020-01-11T12:00:01Z", self.session_1_id, {
                "page": "/home", 
                "user_agent": "Chrome",
                "custom_field": "test_value"
            }),
        ])
        
        flush_persons_and_events()

        with freeze_time("2020-01-11T16:00:00"):
            # Query with custom field selection
            query = create_session_batch_query(
                session_ids=[self.session_1_id],
                select=["event", "properties.page", "properties.custom_field"],
                after="-24h",
            )

            runner = SessionBatchEventsQueryRunner(query=query, team=self.team)
            response = runner.calculate()

            # Verify custom columns are returned
            expected_columns = ["event", "properties.page", "properties.custom_field"]
            self.assertEqual(response.columns, expected_columns)
            
            # Verify event data matches selected fields
            session_1 = response.session_events[0]
            event_row = session_1.events[0]
            
            self.assertEqual(event_row[0], "$pageview")  # event
            self.assertEqual(event_row[1], "/home")      # properties.page
            self.assertEqual(event_row[2], "test_value") # properties.custom_field