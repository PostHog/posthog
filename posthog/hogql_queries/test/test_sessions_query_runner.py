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

from parameterized import parameterized

from posthog.schema import CachedSessionsQueryResponse, PersonPropertyFilter, PropertyOperator, SessionsQuery

from posthog.hogql import ast

from posthog.hogql_queries.sessions_query_runner import (
    HOGQL_COMMENT_SEPARATOR,
    HOGQL_IDENTIFIER_RE,
    PERSON_DISTINCT_IDS_ALIAS,
    PERSON_LOOKUP_ALIAS,
    PERSON_PROPERTY_PREFIX,
    SessionsQueryRunner,
)
from posthog.models.utils import uuid7


class TestSessionsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _create_test_sessions(
        self,
        data: list[tuple[str, str, str, dict[str, Any]]],
        person_properties: dict[str, dict[str, Any]] | None = None,
    ) -> list:
        persons = []
        distinct_ids_seen = set()
        session_id_map: dict[str, str] = {}

        for distinct_id, session_key, timestamp, event_properties in data:
            if session_key not in session_id_map:
                session_id_map[session_key] = str(uuid7(timestamp))

            session_id = session_id_map[session_key]

            with freeze_time(timestamp):
                if distinct_id not in distinct_ids_seen:
                    props = (
                        person_properties.get(distinct_id, {})
                        if person_properties
                        else {
                            "name": f"Person {distinct_id}",
                            "email": f"{distinct_id}@posthog.com",
                        }
                    )
                    persons.append(
                        _create_person(
                            team_id=self.team.pk,
                            distinct_ids=[distinct_id],
                            properties=props,
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

    # ── Basic session queries ───────────────────────────────────────────

    @also_test_with_different_timezones
    @snapshot_clickhouse_queries
    def test_basic_sessions_query(self):
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
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=[],
        )

        runner = SessionsQueryRunner(query=query, team=self.team)

        assert runner.select_input_raw() == ["*"]

    def test_select_input_raw_returns_select(self):
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "distinct_id"],
        )

        runner = SessionsQueryRunner(query=query, team=self.team)

        assert runner.select_input_raw() == ["session_id", "distinct_id"]

    # ── Person join detection ───────────────────────────────────────────

    @parameterized.expand(
        [
            ("person_display_name_in_select", ["person_display_name", "session_id"], None, None, True),
            ("person_property_in_select", ["person.properties.email", "session_id"], None, None, True),
            (
                "person_property_with_comment",
                ["person.properties.email -- Email", "session_id"],
                None,
                None,
                True,
            ),
            ("plain_session_columns", ["session_id", "$start_timestamp"], None, None, False),
            (
                "person_display_name_in_order_by",
                ["session_id"],
                ["person_display_name ASC"],
                None,
                True,
            ),
            (
                "person_property_in_order_by",
                ["session_id"],
                ["person.properties.email ASC"],
                None,
                True,
            ),
            (
                "person_filter_in_properties",
                ["session_id"],
                None,
                [PersonPropertyFilter(key="email", value="test", operator=PropertyOperator.EXACT)],
                True,
            ),
            ("no_person_references", ["session_id"], None, None, False),
        ]
    )
    def test_needs_person_join(self, _name, select, order_by, properties, expected):
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=select,
            orderBy=order_by,
            properties=properties,
        )
        runner = SessionsQueryRunner(query=query, team=self.team)
        assert runner._needs_person_join() == expected

    # ── Person display name ─────────────────────────────────────────────

    @snapshot_clickhouse_queries
    def test_person_display_name_column(self):
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com", "name": "Alice"},
                "user2": {"email": "bob@posthog.com", "name": "Bob"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person_display_name"],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

            display_names = {row[1]["display_name"] for row in response.results}
            assert "alice@posthog.com" in display_names
            assert "bob@posthog.com" in display_names

            for row in response.results:
                person_data = row[1]
                assert "display_name" in person_data
                assert "id" in person_data
                assert "distinct_id" in person_data

    # ── Person property columns ─────────────────────────────────────────

    @snapshot_clickhouse_queries
    def test_person_property_as_column(self):
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
                ("user2", "session2", "2024-01-01T13:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com"},
                "user2": {"email": "bob@posthog.com"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email -- Email"],
                orderBy=["person.properties.email ASC"],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "bob@posthog.com"]

    @snapshot_clickhouse_queries
    def test_star_with_person_join_qualifies_fields(self):
        self._create_test_sessions(
            data=[
                ("user1", "session1", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["*", "person_display_name"],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1

    # ── Person property filter operators ────────────────────────────────

    def _setup_persons_for_filter_tests(self):
        self._create_test_sessions(
            data=[
                ("alice", "s1", "2024-01-01T12:00:00Z", {}),
                ("bob", "s2", "2024-01-01T12:00:00Z", {}),
                ("charlie", "s3", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "alice": {"email": "alice@posthog.com", "age": "30", "plan": "enterprise", "score": "85"},
                "bob": {"email": "bob@example.org", "age": "25", "plan": "free", "score": "42"},
                "charlie": {"email": "charlie@posthog.com", "age": "35", "plan": "pro", "score": "70"},
            },
        )
        flush_persons_and_events()

    @snapshot_clickhouse_queries
    def test_person_property_filter_exact(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="plan", value="enterprise", operator=PropertyOperator.EXACT),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "alice@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_exact_list(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="plan", value=["enterprise", "pro"], operator=PropertyOperator.EXACT),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "charlie@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_property_filter_is_not(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="plan", value="free", operator=PropertyOperator.IS_NOT),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "charlie@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_property_filter_icontains(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="email", value="posthog", operator=PropertyOperator.ICONTAINS),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "charlie@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_property_filter_not_icontains(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="email", value="posthog", operator=PropertyOperator.NOT_ICONTAINS),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "bob@example.org"

    @snapshot_clickhouse_queries
    def test_person_property_filter_regex(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="email", value="^(alice|bob)@", operator=PropertyOperator.REGEX),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2

    @snapshot_clickhouse_queries
    def test_person_property_filter_not_regex(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="email", value="^alice@", operator=PropertyOperator.NOT_REGEX),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert "alice@posthog.com" not in emails

    @snapshot_clickhouse_queries
    def test_person_property_filter_is_set(self):
        self._create_test_sessions(
            data=[
                ("user1", "s1", "2024-01-01T12:00:00Z", {}),
                ("user2", "s2", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com", "phone": "+1234"},
                "user2": {"email": "bob@posthog.com"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="phone", value="", operator=PropertyOperator.IS_SET),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "alice@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_is_not_set(self):
        self._create_test_sessions(
            data=[
                ("user1", "s1", "2024-01-01T12:00:00Z", {}),
                ("user2", "s2", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com", "phone": "+1234"},
                "user2": {"email": "bob@posthog.com"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="phone", value="", operator=PropertyOperator.IS_NOT_SET),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "bob@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_gt(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value="30", operator=PropertyOperator.GT),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "charlie@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_gte(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value="30", operator=PropertyOperator.GTE),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "charlie@posthog.com"]

    @snapshot_clickhouse_queries
    def test_person_property_filter_lt(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value="30", operator=PropertyOperator.LT),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "bob@example.org"

    @snapshot_clickhouse_queries
    def test_person_property_filter_lte(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value="30", operator=PropertyOperator.LTE),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["alice@posthog.com", "bob@example.org"]

    @snapshot_clickhouse_queries
    def test_person_property_filter_is_date_before(self):
        self._create_test_sessions(
            data=[
                ("user1", "s1", "2024-01-01T12:00:00Z", {}),
                ("user2", "s2", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com", "signup_date": "2024-01-01"},
                "user2": {"email": "bob@posthog.com", "signup_date": "2024-06-15"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(
                        key="signup_date", value="2024-03-01", operator=PropertyOperator.IS_DATE_BEFORE
                    ),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "alice@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_is_date_after(self):
        self._create_test_sessions(
            data=[
                ("user1", "s1", "2024-01-01T12:00:00Z", {}),
                ("user2", "s2", "2024-01-01T12:00:00Z", {}),
            ],
            person_properties={
                "user1": {"email": "alice@posthog.com", "signup_date": "2024-01-01"},
                "user2": {"email": "bob@posthog.com", "signup_date": "2024-06-15"},
            },
        )
        flush_persons_and_events()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(
                        key="signup_date", value="2024-03-01", operator=PropertyOperator.IS_DATE_AFTER
                    ),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "bob@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_between(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value=["28", "32"], operator=PropertyOperator.BETWEEN),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 1
            assert response.results[0][1] == "alice@posthog.com"

    @snapshot_clickhouse_queries
    def test_person_property_filter_not_between(self):
        self._setup_persons_for_filter_tests()

        with freeze_time("2024-01-01T14:00:00Z"):
            query = SessionsQuery(
                after="2024-01-01",
                kind="SessionsQuery",
                select=["session_id", "person.properties.email"],
                properties=[
                    PersonPropertyFilter(key="age", value=["28", "32"], operator=PropertyOperator.NOT_BETWEEN),
                ],
            )
            runner = SessionsQueryRunner(query=query, team=self.team)
            response = runner.run()

            assert isinstance(response, CachedSessionsQueryResponse)
            assert len(response.results) == 2
            emails = sorted([row[1] for row in response.results])
            assert emails == ["bob@example.org", "charlie@posthog.com"]

    # ── Person join structure ───────────────────────────────────────────

    def test_person_join_adds_left_joins(self):
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "person_display_name"],
        )
        runner = SessionsQueryRunner(query=query, team=self.team)
        ast_query = runner.to_query()

        assert ast_query.select_from is not None
        pdi_join = ast_query.select_from.next_join
        assert pdi_join is not None
        assert pdi_join.alias == PERSON_DISTINCT_IDS_ALIAS
        assert pdi_join.join_type == "LEFT JOIN"

        persons_join = pdi_join.next_join
        assert persons_join is not None
        assert persons_join.alias == PERSON_LOOKUP_ALIAS
        assert persons_join.join_type == "LEFT JOIN"

    def test_no_person_join_without_person_columns(self):
        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "$start_timestamp"],
        )
        runner = SessionsQueryRunner(query=query, team=self.team)
        ast_query = runner.to_query()

        assert ast_query.select_from is not None
        assert ast_query.select_from.next_join is None

    # ── personId distinct_id is qualified with sessions alias ───────────

    def test_person_id_filter_qualifies_distinct_id(self):
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["user1"],
            properties={"email": "user1@test.com"},
        )
        flush_persons_and_events()

        from posthog.models import Person
        from posthog.models.person.person import READ_DB_FOR_PERSONS

        person = Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team=self.team).first()
        assert person is not None

        query = SessionsQuery(
            after="2024-01-01",
            kind="SessionsQuery",
            select=["session_id", "person_display_name"],
            personId=str(person.pk),
        )
        runner = SessionsQueryRunner(query=query, team=self.team)
        ast_query = runner.to_query()

        # Walk the WHERE clause to find the cityHash64 call on distinct_id
        assert ast_query.where is not None

        def find_cityhash_field(expr: ast.Expr) -> ast.Field | None:
            if isinstance(expr, ast.And):
                for e in expr.exprs:
                    result = find_cityhash_field(e)
                    if result:
                        return result
            if isinstance(expr, ast.CompareOperation):
                if isinstance(expr.left, ast.Call) and expr.left.name == "cityHash64":
                    arg = expr.left.args[0]
                    if isinstance(arg, ast.Field):
                        return arg
            return None

        field = find_cityhash_field(ast_query.where)
        assert field is not None
        assert field.chain == ["sessions", "distinct_id"]

    # ── Column/comment utilities ────────────────────────────────────────

    @parameterized.expand(
        [
            ("plain_column", "session_id", ("session_id", None)),
            ("column_with_comment", "person.properties.email -- Email", ("person.properties.email", "Email")),
            ("column_with_multi_dash", "expr -- a -- b", ("expr", "a -- b")),
        ]
    )
    def test_split_col_comment(self, _name, col, expected):
        query = SessionsQuery(after="2024-01-01", kind="SessionsQuery", select=["session_id"])
        runner = SessionsQueryRunner(query=query, team=self.team)
        assert runner._split_col_comment(col) == expected

    @parameterized.expand(
        [
            ("simple_identifier", "email", True),
            ("dollar_prefix", "$browser", True),
            ("underscore_prefix", "_private", True),
            ("with_digits", "prop123", True),
            ("starts_with_digit", "123prop", False),
            ("has_space", "my prop", False),
            ("has_dot", "a.b", False),
        ]
    )
    def test_hogql_identifier_regex(self, _name, value, expected):
        assert bool(HOGQL_IDENTIFIER_RE.match(value)) == expected

    # ── Constants are used throughout ───────────────────────────────────

    def test_constants_are_consistent(self):
        assert HOGQL_COMMENT_SEPARATOR == "--"
        assert PERSON_PROPERTY_PREFIX == "person.properties."
        assert PERSON_DISTINCT_IDS_ALIAS == "__pdi"
        assert PERSON_LOOKUP_ALIAS == "__person_lookup"
