from typing import Any

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

from posthog.schema import CachedSessionsQueryResponse, SessionsQuery

from posthog.hogql_queries.sessions_query_runner import SessionsQueryRunner
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
