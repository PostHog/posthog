from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    also_test_with_different_timezones,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized

from posthog.schema import (
    CachedSessionsQueryResponse,
    EventPropertyFilter,
    PersonPropertyFilter,
    SessionPropertyFilter,
    SessionsQuery,
)

from posthog.hogql.printer import to_printed_hogql

from posthog.hogql_queries.sessions_query_runner import SUPPORTED_PERSON_PROPERTY_OPERATORS, SessionsQueryRunner
from posthog.models.utils import uuid7


class TestSessionsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_sessions(self, data: list[tuple[str, str, str, dict[str, Any]]]) -> list:
        """Create test sessions with persons and events.

        Args:
            data: List of tuples (distinct_id, session_key, timestamp, event_properties)

        Returns:
            List of created Person objects
        """
        persons = []
        distinct_ids_seen = set()
        session_id_map: dict[str, str] = {}

        for distinct_id, session_key, timestamp, event_properties in data:
            if session_key not in session_id_map:
                session_id_map[session_key] = str(uuid7(timestamp))

            session_id = session_id_map[session_key]

            with freeze_time(timestamp):
                if distinct_id not in distinct_ids_seen:
                    persons.append(
                        _create_person(
                            team_id=self.team.pk,
                            distinct_ids=[distinct_id],
                            properties={
                                "name": f"Person {distinct_id}",
                                "email": f"{distinct_id}@posthog.com",
                            },
                        )
                    )
                    distinct_ids_seen.add(distinct_id)

                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    properties={**event_properties, "$session_id": session_id},
                )

        return persons

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_basic_sessions_query(self):
        """Test basic sessions query returns correct number of sessions."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user1", "session1", "2024-01-01T12:05:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["*"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

    @snapshot_clickhouse_queries
    def test_sessions_with_aggregation(self):
        """Test sessions query can aggregate by distinct_id and count sessions."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {"$current_url": "https://posthog.com/"}),
                ("user1", "session1", "2024-01-01T12:05:00Z", {"$current_url": "https://posthog.com/about"}),
                ("user1", "session2", "2024-01-01T13:00:00Z", {"$current_url": "https://posthog.com/pricing"}),
                ("user2", "session3", "2024-01-01T14:00:00Z", {"$current_url": "https://posthog.com/"}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T15:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["distinct_id", "count()"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

            user_sessions = {row[0]: row[1] for row in response.results}
            assert user_sessions["user1"] == 2
            assert user_sessions["user2"] == 1

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_sessions_date_range(self):
        """Test sessions query filters by date range correctly."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user1", "session2", "2024-01-02T12:00:00Z", {}),
                ("user1", "session3", "2024-01-03T12:00:00Z", {}),
                ("user1", "session4", "2024-01-04T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-05T00:00:00Z"):
            query = SessionsQuery(
                after="2024-01-02",
                before="2024-01-03T23:59:59Z",
                kind="SessionsQuery",
                select=["*"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

    @snapshot_clickhouse_queries
    def test_sessions_with_custom_order_by(self):
        """Test sessions query respects custom orderBy clause."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
                ("user3", "session3", "2024-01-01T14:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T15:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$start_timestamp"],
                orderBy=["$start_timestamp ASC"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 3

            timestamps = [row[1] for row in response.results]
            assert timestamps == sorted(timestamps)

    @snapshot_clickhouse_queries
    def test_sessions_with_session_duration(self):
        """Test session duration calculation returns correct values."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user1", "session1", "2024-01-01T12:10:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
                ("user2", "session2", "2024-01-01T13:05:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$session_duration", "$start_timestamp", "$end_timestamp"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

            durations = sorted([row[1] for row in response.results])
            assert durations == [300, 600]

    @snapshot_clickhouse_queries
    def test_sessions_with_where_clause(self):
        """Test sessions query filters by where clause correctly."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user1", "session1", "2024-01-01T12:20:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
                ("user2", "session2", "2024-01-01T13:02:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$session_duration"],
                where=["$session_duration > 300"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_sessions_limit_and_offset(self):
        """Test sessions query pagination with limit and offset."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user2", "session2", "2024-01-01T12:05:00Z", {}),
                ("user3", "session3", "2024-01-01T12:10:00Z", {}),
                ("user4", "session4", "2024-01-01T12:15:00Z", {}),
                ("user5", "session5", "2024-01-01T12:20:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["*"],
                limit=2,
                offset=1,
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

    def test_to_query_generates_hogql_ast(self):
        """Test to_query generates valid HogQL AST structure."""
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "distinct_id", "$start_timestamp"],
        )

        runner = SessionsQueryRunner(query=query, team=self.team)
        ast_query = runner.to_query()

        assert ast_query.select is not None
        assert len(ast_query.select) == 3
        assert ast_query.select_from is not None
        assert ast_query.where is not None

    def test_select_input_raw_defaults_to_star(self):
        """Test select_input_raw defaults to ['*'] when select is empty."""
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=[],
        )

        runner = SessionsQueryRunner(query=query, team=self.team)

        assert runner.select_input_raw() == ["*"]

    def test_select_input_raw_returns_select(self):
        """Test select_input_raw returns provided select fields."""
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "distinct_id"],
        )

        runner = SessionsQueryRunner(query=query, team=self.team)

        assert runner.select_input_raw() == ["session_id", "distinct_id"]

    @snapshot_clickhouse_queries
    def test_person_display_name_field(self):
        """Test person_display_name returns correct dict structure with default properties."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            person_display = response.results[0][1]
            assert isinstance(person_display, dict)
            # Default display name uses email
            assert person_display["display_name"] == "user1@posthog.com"
            assert "id" in person_display
            assert person_display["distinct_id"] == "user1"

    @snapshot_clickhouse_queries
    def test_person_display_name_with_custom_properties(self):
        """Test person_display_name respects team.person_display_name_properties."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        # Set custom display name property
        self.team.person_display_name_properties = ["name"]
        self.team.save()
        self.team.refresh_from_db()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            person_display = response.results[0][1]
            # Should use name property instead of email
            assert person_display["display_name"] == "Person user1"

    @snapshot_clickhouse_queries
    def test_person_display_name_fallback_to_distinct_id(self):
        """Test person_display_name falls back to distinct_id when properties missing."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        # Set property that doesn't exist
        self.team.person_display_name_properties = ["nonexistent_property"]
        self.team.save()
        self.team.refresh_from_db()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            person_display = response.results[0][1]
            # Should fall back to distinct_id
            assert person_display["display_name"] == "user1"

    @snapshot_clickhouse_queries
    def test_person_display_name_with_spaces_in_property_name(self):
        """Test person_display_name handles property names with spaces."""
        # Create person with property that has spaces
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user_spaced"],
            properties={
                "Property With Spaces": "Test User With Spaces",
                "email": "spaced@example.com",
            },
        )
        session_id = str(uuid7("2024-01-01T12:00:00Z"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user_spaced",
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()

        # Set property with spaces as display name
        self.team.person_display_name_properties = ["Property With Spaces"]
        self.team.save()
        self.team.refresh_from_db()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            person_display = response.results[0][1]
            assert person_display["display_name"] == "Test User With Spaces"

    @snapshot_clickhouse_queries
    def test_person_display_name_combined_with_other_columns(self):
        """Test person_display_name works alongside other session columns."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user1", "session1", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person", "$session_duration"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            row = response.results[0]
            assert row[0] is not None  # session_id
            assert isinstance(row[1], dict)  # person_display_name
            assert row[1]["display_name"] == "user1@posthog.com"
            assert row[2] == 600  # 10 minutes duration

    @snapshot_clickhouse_queries
    def test_orderby_person_display_name(self):
        """Test sessions can be ordered by person_display_name."""
        self._create_test_sessions(
            data=[
                ("userA", "session1", "2024-01-01T12:00:00Z", {}),
                ("userB", "session2", "2024-01-01T12:05:00Z", {}),
                ("userC", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
                orderBy=["person_display_name -- Person DESC"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 3

            # Should be ordered by display_name (email) descending
            display_names = [row[1]["display_name"] for row in response.results]
            assert display_names == ["userC@posthog.com", "userB@posthog.com", "userA@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_display_name_multiple_persons(self):
        """Test person_display_name correctly resolves different persons for different sessions."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
                orderBy=["person_display_name -- Person ASC"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 3

            display_names = [row[1]["display_name"] for row in response.results]
            assert display_names == ["alice@posthog.com", "bob@posthog.com", "charlie@posthog.com"]
            for row in response.results:
                assert isinstance(row[1], dict)
                assert row[1]["id"] is not None
                assert row[1]["distinct_id"] is not None

    @snapshot_clickhouse_queries
    def test_person_display_name_with_star_select(self):
        """Test person_display_name works alongside star select."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["*", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

            row = response.results[0]
            assert isinstance(row[0], dict)  # star select returns dict
            assert isinstance(row[1], dict)  # person_display_name returns dict
            assert row[1]["display_name"] == "user1@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_display_name_without_person_join_no_regression(self):
        """Test queries without person_display_name don't include person joins."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$session_duration", "$start_timestamp"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            assert not runner._needs_person_join()

            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_arbitrary_person_property_field(self):
        """Test arbitrary person.properties.X columns work."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            assert runner._needs_person_join()

            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "user1@posthog.com"

    @snapshot_clickhouse_queries
    def test_arbitrary_person_property_with_comment(self):
        """Test person.properties.X with comment alias works."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.name -- Name"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "Person user1"

    @snapshot_clickhouse_queries
    def test_arbitrary_person_property_orderby(self):
        """Test ordering by arbitrary person properties."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                orderBy=["person.properties.email ASC"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 3
            emails = [row[1] for row in response.results]
            assert emails == ["alice@posthog.com", "bob@posthog.com", "charlie@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_property_combined_with_display_name(self):
        """Test combining person.properties.X with person_display_name."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person", "person.properties.name"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1]["display_name"] == "user1@posthog.com"
            assert response.results[0][2] == "Person user1"

    @snapshot_clickhouse_queries
    def test_filter_by_person_property(self):
        """Test filtering sessions by person property."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="email", value="bob@posthog.com", operator="exact", type="person")
                ],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            assert runner._needs_person_join()

            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "bob@posthog.com"

    @snapshot_clickhouse_queries
    def test_filter_by_person_property_icontains(self):
        """Test filtering sessions by person property with icontains operator."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[PersonPropertyFilter(key="email", value="alice", operator="icontains", type="person")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "alice@posthog.com"

    @snapshot_clickhouse_queries
    def test_filter_by_person_property_without_person_column(self):
        """Test filtering by person property without selecting person columns."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$session_duration"],
                properties=[PersonPropertyFilter(key="name", value="Person alice", operator="exact", type="person")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            assert runner._needs_person_join()

            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

    @snapshot_clickhouse_queries
    def test_session_property_column(self):
        """Test selecting session properties like $channel_type using session.X syntax."""
        session_id = str(uuid7("2024-01-01T12:00:00Z"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user1"],
            properties={"email": "user1@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T12:00:00Z",
            properties={
                "$session_id": session_id,
                "$referring_domain": "google.com",
                "gclid": "test123",
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "session.$channel_type"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            # Should have resolved the channel type
            assert response.results[0][1] is not None

    @snapshot_clickhouse_queries
    def test_session_property_with_person_property(self):
        """Test combining session.X properties with person properties."""
        session_id = str(uuid7("2024-01-01T12:00:00Z"))
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user1"],
            properties={"email": "user1@posthog.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user1",
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "session.$entry_current_url", "person.properties.email"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            assert runner._needs_person_join()

            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][2] == "user1@posthog.com"

    @snapshot_clickhouse_queries
    def test_anonymous_session_identified_later(self):
        """Test that anonymous sessions that get identified later still resolve person properties."""
        session_id = str(uuid7("2024-01-01T12:00:00Z"))
        anon_distinct_id = "anon_user_123"
        identified_distinct_id = "identified_user"

        # Create the person with the identified distinct_id
        _create_person(
            team_id=self.team.pk,
            distinct_ids=[identified_distinct_id, anon_distinct_id],
            properties={"email": "identified@posthog.com", "name": "Identified User"},
        )

        # Session started with anonymous distinct_id
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=anon_distinct_id,
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session_id},
        )
        # Later in the same session, user identifies
        _create_event(
            team=self.team,
            event="$identify",
            distinct_id=identified_distinct_id,
            timestamp="2024-01-01T12:05:00Z",
            properties={"$session_id": session_id, "$anon_distinct_id": anon_distinct_id},
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person", "person.properties.email"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            # Should resolve to the identified person's properties
            person_display = response.results[0][1]
            assert person_display["display_name"] == "identified@posthog.com"
            assert response.results[0][2] == "identified@posthog.com"

    @snapshot_clickhouse_queries
    def test_anonymous_session_not_identified(self):
        """Test that sessions that remain anonymous fall back to distinct_id."""
        session_id = str(uuid7("2024-01-01T12:00:00Z"))
        anon_distinct_id = "anon_user_456"

        # No person created - session remains anonymous
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=anon_distinct_id,
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session_id},
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name -- Person"],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            # Should fall back to distinct_id since no person exists
            person_display = response.results[0][1]
            assert person_display["display_name"] == anon_distinct_id
            assert person_display["distinct_id"] == anon_distinct_id

    def test_unsupported_person_property_operator_raises_error(self):
        """Test that unsupported operators raise ValueError."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                properties=[PersonPropertyFilter(key="email", value="test", operator="is_date_after", type="person")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            with pytest.raises(ValueError) as exc_info:
                runner.run()

            assert "Unsupported operator 'is_date_after'" in str(exc_info.value)
            assert "Supported operators:" in str(exc_info.value)

    @parameterized.expand(
        [
            ("exact_match", "exact", "user1@posthog.com", True),
            ("exact_no_match", "exact", "other@posthog.com", False),
            ("is_not_match", "is_not", "other@posthog.com", True),
            ("is_not_no_match", "is_not", "user1@posthog.com", False),
            ("icontains_match", "icontains", "user1", True),
            ("icontains_no_match", "icontains", "nobody", False),
            ("not_icontains_match", "not_icontains", "nobody", True),
            ("not_icontains_no_match", "not_icontains", "user1", False),
            ("regex_match", "regex", r"user\d+@posthog\.com", True),
            ("regex_no_match", "regex", r"admin@.*", False),
            ("not_regex_match", "not_regex", r"admin@.*", True),
            ("not_regex_no_match", "not_regex", r"user\d+@posthog\.com", False),
            ("is_set_match", "is_set", None, True),
            ("is_not_set_no_match", "is_not_set", None, False),
        ],
    )
    def test_person_property_filter_operators(self, _name, operator, value, expected_match):
        """Test that all supported person property operators work correctly."""
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                properties=[PersonPropertyFilter(key="email", value=value, operator=operator, type="person")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            if expected_match:
                assert len(response.results) == 1, (
                    f"Expected 1 result for operator '{operator}' but got {len(response.results)}"
                )
            else:
                assert len(response.results) == 0, (
                    f"Expected 0 results for operator '{operator}' but got {len(response.results)}"
                )

    @parameterized.expand(
        [
            ("gt_match", "gt", 20, True),
            ("gt_no_match", "gt", 30, False),
            ("lt_match", "lt", 30, True),
            ("lt_no_match", "lt", 20, False),
            ("gte_match_greater", "gte", 20, True),
            ("gte_match_equal", "gte", 25, True),
            ("gte_no_match", "gte", 30, False),
            ("lte_match_less", "lte", 30, True),
            ("lte_match_equal", "lte", 25, True),
            ("lte_no_match", "lte", 20, False),
        ],
    )
    def test_person_property_filter_numeric_operators(self, _name, operator, value, expected_match):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["numeric_user"],
            properties={"age": 25},
        )

        with freeze_time("2024-01-01T12:00:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="numeric_user",
                timestamp="2024-01-01T12:00:00Z",
                properties={"$session_id": str(uuid7("2024-01-01T12:00:00Z"))},
            )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                properties=[PersonPropertyFilter(key="age", value=value, operator=operator, type="person")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            if expected_match:
                assert len(response.results) == 1, (
                    f"Expected 1 result for operator '{operator}' with value {value} but got {len(response.results)}"
                )
            else:
                assert len(response.results) == 0, (
                    f"Expected 0 results for operator '{operator}' with value {value} but got {len(response.results)}"
                )

    def test_supported_operators_constant_is_complete(self):
        """Verify that the SUPPORTED_PERSON_PROPERTY_OPERATORS constant contains expected operators."""
        expected_operators = {
            "exact",
            "is_not",
            "icontains",
            "not_icontains",
            "regex",
            "not_regex",
            "is_set",
            "is_not_set",
            "gt",
            "lt",
            "gte",
            "lte",
        }
        assert SUPPORTED_PERSON_PROPERTY_OPERATORS == expected_operators

    @snapshot_clickhouse_queries
    def test_filter_by_event_properties_without_event_name(self):
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {"$current_url": "https://example.com/pricing"}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {"$current_url": "https://example.com/about"}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {"$current_url": "https://example.com/pricing"}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                eventProperties=[
                    EventPropertyFilter(
                        key="$current_url", value="https://example.com/pricing", operator="exact", type="event"
                    )
                ],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

    def test_session_id_event_property_filter_short_circuits_events_subquery(self):
        """When eventProperties only contains a $session_id filter, we should filter
        directly on the sessions table without building an events subquery."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            # Get session IDs first
            all_query = SessionsQuery(after="2024-01-01", kind="SessionsQuery", select=["session_id"])
            all_response = SessionsQueryRunner(query=all_query, team=self.team).run()
            assert isinstance(all_response, CachedSessionsQueryResponse)
            assert len(all_response.results) == 2
            target_session_id = all_response.results[0][0]

            # Filter by $session_id as an event property — should short-circuit
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                eventProperties=[
                    EventPropertyFilter(key="$session_id", value=target_session_id, operator="exact", type="event")
                ],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][0] == target_session_id
            # The generated HogQL should NOT contain "FROM events"
            assert "FROM events" not in response.hogql

    def test_session_id_event_property_filter_with_list_values(self):
        """$session_id filter with a list of values should short-circuit."""
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            all_query = SessionsQuery(after="2024-01-01", kind="SessionsQuery", select=["session_id"])
            all_response = SessionsQueryRunner(query=all_query, team=self.team).run()
            assert isinstance(all_response, CachedSessionsQueryResponse)
            session_ids = [r[0] for r in all_response.results]

            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                eventProperties=[
                    EventPropertyFilter(key="$session_id", value=session_ids[:2], operator="exact", type="event")
                ],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            assert "FROM events" not in response.hogql

    def test_session_id_event_property_filter_empty_list_returns_no_sessions(self):
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                eventProperties=[EventPropertyFilter(key="$session_id", value=[], operator="exact", type="event")],
            )
            response = SessionsQueryRunner(query=query, team=self.team).run()
            assert isinstance(response, CachedSessionsQueryResponse)
            assert response.results == []

    def test_session_id_event_property_with_other_event_filters_keeps_subquery(self):
        """When $session_id is combined with an event name filter, we still need the events subquery
        for the event filter, but $session_id is applied directly to sessions."""
        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                event="$pageview",
                eventProperties=[
                    EventPropertyFilter(key="$session_id", value="test-session-id", operator="exact", type="event")
                ],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            hogql = runner.to_query()

            from posthog.hogql.printer import to_printed_hogql

            printed = to_printed_hogql(hogql, team=self.team)
            # $session_id should be filtered directly on sessions
            assert "in(session_id, tuple('test-session-id'))" in printed
            # Events subquery should still exist for the event name filter
            assert "events" in printed

    @snapshot_clickhouse_queries
    def test_filter_by_session_properties(self):
        self._create_test_sessions(
            data=[
                ("alice", "session1", "2024-01-01T12:00:00Z", {}),
                ("bob", "session2", "2024-01-01T12:05:00Z", {}),
                ("charlie", "session3", "2024-01-01T12:10:00Z", {}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "$session_duration"],
                properties=[SessionPropertyFilter(key="$session_duration", value=0, operator="gte", type="session")],
            )

            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 3

    def test_default_after_is_one_hour(self):
        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(kind="SessionsQuery", select=["session_id"])
            runner = SessionsQueryRunner(query=query, team=self.team)
            printed = to_printed_hogql(runner.to_query(), team=self.team)

            # With no explicit `after`, the lower bound must be one hour before `now`
            # (13:00:00), not 24h earlier. The exact printed format depends on timezone
            # conversion; asserting the hour is enough to catch regressions.
            assert "13:00:00" in printed

    def test_filter_test_accounts_with_event_property(self):
        self.team.test_account_filters = [{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}]
        self.team.save()

        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {"$browser": "Chrome"}),
                ("user2", "session2", "2024-01-01T12:05:00Z", {"$browser": "Firefox"}),
            ]
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                filterTestAccounts=True,
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            # Only the Chrome session should match (event filter routes through events subquery)
            assert len(response.results) == 1

    def test_filter_test_accounts_with_person_property(self):
        self.team.test_account_filters = [
            {"key": "email", "value": "@test.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["real_user"],
            properties={"email": "real@company.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["test_user"],
            properties={"email": "bot@test.com"},
        )

        session1 = str(uuid7("2024-01-01T12:00:00Z"))
        session2 = str(uuid7("2024-01-01T12:05:00Z"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="real_user",
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test_user",
            timestamp="2024-01-01T12:05:00Z",
            properties={"$session_id": session2},
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                filterTestAccounts=True,
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            # Only the real user session should remain (test.com email excluded)
            assert len(response.results) == 1

    def test_filter_test_accounts_with_cohort_filter(self):
        from posthog.models import Cohort

        cohort = Cohort.objects.create(
            team=self.team,
            name="Test Users",
            groups=[
                {"properties": [{"key": "email", "value": "@test.com", "operator": "icontains", "type": "person"}]}
            ],
        )

        self.team.test_account_filters = [{"key": "id", "type": "cohort", "value": cohort.pk, "operator": "not_in"}]
        self.team.save()

        _create_person(
            team_id=self.team.pk,
            distinct_ids=["real_user"],
            properties={"email": "real@company.com"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["test_user"],
            properties={"email": "bot@test.com"},
        )

        session1 = str(uuid7("2024-01-01T12:00:00Z"))
        session2 = str(uuid7("2024-01-01T12:05:00Z"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="real_user",
            timestamp="2024-01-01T12:00:00Z",
            properties={"$session_id": session1},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="test_user",
            timestamp="2024-01-01T12:05:00Z",
            properties={"$session_id": session2},
        )
        flush_persons_and_events()

        cohort.calculate_people_ch(pending_version=0)

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                filterTestAccounts=True,
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            # Should not raise — cohort filter routes through events subquery
            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
            # Cohort filter should actually exclude the test user
            assert len(response.results) == 1

    def test_filter_test_accounts_with_session_property(self):
        self.team.test_account_filters = [
            {"key": "$is_bounce", "value": "true", "operator": "exact", "type": "session"}
        ]
        self.team.save()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id"],
                filterTestAccounts=True,
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            # Should not raise — session property applied directly
            response = runner.run()
            assert isinstance(response, CachedSessionsQueryResponse)
