from typing import Optional

from freezegun.api import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    SessionTableVersion,
    WebGoalsQuery,
)

from posthog.hogql.test.utils import pretty_print_in_tests

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.web_analytics.web_goals import WebGoalsQueryRunner
from posthog.models import Action, Cohort, Element, Person
from posthog.models.person.sql import PERSON_DISTINCT_ID_OVERRIDES_TABLE
from posthog.models.utils import uuid7


@snapshot_clickhouse_queries
class TestWebGoalsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"
    EVENT_TIMESTAMP = "2024-12-01"

    def _create_person(self):
        with freeze_time(self.EVENT_TIMESTAMP):
            distinct_id = self._uuid()
            session_id = self._uuid()
            p = _create_person(
                uuid=distinct_id,
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                properties={
                    "name": distinct_id,
                },
            )
            # do a pageview with this person so that they show up in results even if they don't perform a goal
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id,
                properties={"$session_id": session_id},
            )
            return p, session_id

    def _visit_web_analytics(self, person: Person, session_id: Optional[str] = None):
        with freeze_time(self.EVENT_TIMESTAMP):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=person.uuid,
                timestamp=self.EVENT_TIMESTAMP,
                properties={
                    "$pathname": "/project/2/web",
                    "$current_url": "https://us.posthog.com/project/2/web",
                    "$session_id": session_id or person.uuid,
                },
            )

    def _click_pay(self, person: Person, session_id: Optional[str] = None):
        with freeze_time(self.EVENT_TIMESTAMP):
            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=person.uuid,
                timestamp=self.EVENT_TIMESTAMP,
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
                properties={"$session_id": session_id or person.uuid},
            )

    def _create_actions(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            a0 = Action.objects.create(
                team=self.team,
                name="Clicked Pay",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Pay $10",
                    }
                ],
                last_calculated_at=self.EVENT_TIMESTAMP,  # oldest
            )
            a1 = Action.objects.create(
                team=self.team,
                name="Contacted Sales",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "tag_name": "button",
                        "text": "Contacted Sales",
                    }
                ],
                pinned_at=self.QUERY_TIMESTAMP,
                last_calculated_at=self.QUERY_TIMESTAMP,
            )
            a2 = Action.objects.create(
                team=self.team,
                name="Visited Web Analytics",
                steps_json=[
                    {
                        "event": "$pageview",
                        "url": "https://(app|eu|us)\\.posthog\\.com/project/\\d+/web.*",
                        "url_matching": "regex",
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,  # newest
            )
            return a0, a1, a2

    def _run_web_goals_query(
        self,
        date_from,
        date_to,
        limit=None,
        path_cleaning_filters=None,
        properties=None,
        compare=True,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
            query = WebGoalsQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=properties or [],
                limit=limit,
                filterTestAccounts=filter_test_accounts,
                compareFilter=CompareFilter(compare=compare),
            )
            self.team.path_cleaning_filters = path_cleaning_filters or []
            runner = WebGoalsQueryRunner(team=self.team, query=query, modifiers=modifiers)
            return runner.calculate()

    def _uuid(self):
        with freeze_time(self.EVENT_TIMESTAMP):
            return str(uuid7())

    def test_no_crash_when_no_data_or_actions(self):
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == []

    def test_no_crash_when_no_data_and_some_actions(self):
        self._create_actions()
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (0, 0), (0, 0), (0, 0)],
            ["Clicked Pay", (0, 0), (0, 0), (0, 0)],
        ]

    def test_no_comparison(self):
        self._create_actions()
        p1, s1 = self._create_person()
        self._visit_web_analytics(p1, s1)

        results = self._run_web_goals_query("2024-11-01", None, compare=False).results
        assert results == [
            ["Contacted Sales", (0, None), (0, None), (0, None)],
            ["Visited Web Analytics", (1, None), (1, None), (1, None)],
            ["Clicked Pay", (0, None), (0, None), (0, None)],
        ]

    def test_one_user_one_action(self):
        self._create_actions()
        p1, s1 = self._create_person()
        self._visit_web_analytics(p1, s1)
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (1, 0), (1, 0), (1, 0)],
            ["Clicked Pay", (0, 0), (0, 0), (0, 0)],
        ]

    def test_one_user_two_similar_actions_across_sessions(self):
        self._create_actions()
        p1, s1 = self._create_person()
        self._visit_web_analytics(p1, s1)
        s2 = self._uuid()
        self._visit_web_analytics(p1, s2)
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (1, 0), (2, 0), (1, 0)],
            ["Clicked Pay", (0, 0), (0, 0), (0, 0)],
        ]

    def test_one_user_two_different_actions(self):
        self._create_actions()
        p1, s1 = self._create_person()
        self._visit_web_analytics(p1, s1)
        self._click_pay(p1, s1)
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (1, 0), (1, 0), (1, 0)],
            ["Clicked Pay", (1, 0), (1, 0), (1, 0)],
        ]

    def test_one_users_one_action_each(self):
        self._create_actions()
        p1, s1 = self._create_person()
        p2, s2 = self._create_person()
        self._visit_web_analytics(p1, s1)
        self._click_pay(p2, s2)
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (1, 0), (1, 0), (0.5, 0)],
            ["Clicked Pay", (1, 0), (1, 0), (0.5, 0)],
        ]

    def test_many_users_and_actions(self):
        self._create_actions()
        # create some users who visited web analytics
        for _ in range(8):
            p, s = self._create_person()
            self._visit_web_analytics(p, s)
        # create some users who clicked pay
        for _ in range(4):
            p, s = self._create_person()
            self._click_pay(p, s)
        # create some users who did both
        for _ in range(2):
            p, s = self._create_person()
            self._visit_web_analytics(p, s)
            self._click_pay(p, s)
        # create one user who did both twice
        for _ in range(1):
            p, s = self._create_person()
            self._visit_web_analytics(p, s)
            self._visit_web_analytics(p, s)
            self._click_pay(p, s)
            self._click_pay(p, s)

        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (11, 0), (12, 0), (11 / 15, 0)],
            ["Clicked Pay", (7, 0), (8, 0), (7 / 15, 0)],
        ]

    def test_dont_show_deleted_actions(self):
        actions = self._create_actions()
        p1, s1 = self._create_person()
        p2, s2 = self._create_person()
        self._visit_web_analytics(p1, s1)
        self._click_pay(p2, s2)
        actions[0].delete()
        results = self._run_web_goals_query("2024-11-01", None).results
        assert results == [
            ["Contacted Sales", (0, 0), (0, 0), (0, 0)],
            ["Visited Web Analytics", (1, 0), (1, 0), (0.5, 0)],
        ]

    def test_aggregate_function_in_where_error(self):
        """Test cohort with multiple actions that produced the aggregate function in WHERE clause error:
        Aggregate function any(if(NOT empty(events__override.distinct_id), events__override.person_id, events.person_id))AS person_id is found in WHERE in query."""
        with freeze_time(self.QUERY_TIMESTAMP):
            cohort = Cohort.objects.create(
                team=self.team,
                filters={
                    "properties": {
                        "type": "OR",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {"key": "name", "type": "person", "value": ["test_user"], "operator": "exact"}
                                ],
                            }
                        ],
                    }
                },
                name="Test Cohort",
            )

        # Create multiple actions to generate complex query
        with freeze_time(self.QUERY_TIMESTAMP):
            Action.objects.create(
                team=self.team,
                name="Test Action 1",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": '[data-node-key="interactions"]',
                        "url": "https://teest.com",
                        "url_matching": "contains",
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": cohort.pk,
                            }
                        ],
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,
            )

            Action.objects.create(
                team=self.team,
                name="Test Action 2",
                steps_json=[
                    {
                        "event": "$pageview",
                        "url": "https://teest.com",
                        "url_matching": "contains",
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,
            )

            Action.objects.create(
                team=self.team,
                name="Test Action 3",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": ".ant-input",
                        "url": "https://teest.com",
                        "url_matching": "contains",
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,
            )

            Action.objects.create(
                team=self.team,
                name="Test Action 4",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": ".text-white.ant-btn",
                        "text": "text page",
                        "url": "https://teest.com",
                        "url_matching": "exact",
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,
            )

            Action.objects.create(
                team=self.team,
                name="Test Action 5",
                steps_json=[
                    {
                        "event": "$autocapture",
                        "selector": ".ant-btn a",
                        "text": "text",
                        "url": "https://teest.com",
                        "url_matching": "exact",
                    }
                ],
                last_calculated_at=self.QUERY_TIMESTAMP,
            )

        # Create persons with distinct_id overrides to trigger the error
        with freeze_time(self.EVENT_TIMESTAMP):
            # Create persons with different distinct_ids but insert overrides that create conflicts
            distinct_id_1 = self._uuid()
            distinct_id_2 = self._uuid()
            session_id = self._uuid()
            person_id_1 = self._uuid()
            person_id_2 = self._uuid()

            # Create persons with different distinct_ids that match the cohort
            p1 = _create_person(
                uuid=person_id_1,
                team_id=self.team.pk,
                distinct_ids=[distinct_id_1],
                properties={"name": "test_user"},  # This matches the cohort criteria
            )

            p2 = _create_person(
                uuid=person_id_2,
                team_id=self.team.pk,
                distinct_ids=[distinct_id_2],
                properties={"name": "test_user"},  # This also matches the cohort criteria
            )

            # Add persons to the cohort
            cohort.people.add(p1, p2)

            # Insert person_distinct_id_overrides that create the scenario for any() function
            # This creates multiple overrides for the same distinct_id in ClickHouse with the same version
            # This should force the any() function to be used when multiple person_ids exist for the same distinct_id
            # We need to create multiple overrides with the same version to trigger the any() function
            sync_execute(
                f"""
                INSERT INTO {PERSON_DISTINCT_ID_OVERRIDES_TABLE}
                (team_id, distinct_id, person_id, version, is_deleted, _timestamp)
                VALUES
                (%(team_id)s, %(distinct_id_1)s, %(person_id_1)s, %(version)s, %(is_deleted)s, %(timestamp)s),
                (%(team_id)s, %(distinct_id_1)s, %(person_id_2)s, %(version)s, %(is_deleted)s, %(timestamp)s),
                (%(team_id)s, %(distinct_id_1)s, %(person_id_3)s, %(version)s, %(is_deleted)s, %(timestamp)s)
                """,
                {
                    "team_id": self.team.pk,
                    "distinct_id_1": distinct_id_1,
                    "person_id_1": person_id_1,
                    "person_id_2": person_id_2,
                    "person_id_3": self._uuid(),  # Add a third person_id
                    "version": 1,
                    "is_deleted": False,
                    "timestamp": "2024-12-01 00:00:00",
                },
            )

            # Create events that will trigger the complex query structure with multiple actions
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct_id_1,
                timestamp=self.EVENT_TIMESTAMP,
                properties={
                    "$session_id": session_id,
                    "$host": "teest.com",
                    "mat_$host": "teest.com",
                    "$current_url": "https://teest.com",
                    "mat_$current_url": "https://teest.com",
                },
            )

            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=distinct_id_1,
                timestamp=self.EVENT_TIMESTAMP,
                elements=[
                    Element(
                        nth_of_type=1,
                        nth_child=0,
                        tag_name="button",
                        text="Explore page",
                        attr_class=["text-white", "ant-btn"],
                    )
                ],
                properties={
                    "$session_id": session_id,
                    "$host": "teest.com",
                    "mat_$host": "teest.com",
                    "$current_url": "https://teest.com",
                    "mat_$current_url": "https://teest.com",
                },
            )

            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=distinct_id_1,
                timestamp=self.EVENT_TIMESTAMP,
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="input", attr_class=["ant-input"])],
                properties={
                    "$session_id": session_id,
                    "$host": "teest.com",
                    "mat_$host": "teest.com",
                    "$current_url": "https://teest.com",
                    "mat_$current_url": "https://teest.com",
                },
            )

            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=distinct_id_1,
                timestamp=self.EVENT_TIMESTAMP,
                elements=[
                    Element(nth_of_type=1, nth_child=0, tag_name="div", attributes={"data-node-key": "interactions"})
                ],
                properties={
                    "$session_id": session_id,
                    "$host": "teest.com",
                    "mat_$host": "teest.com",
                    "$current_url": "https://teest.com",
                    "mat_$current_url": "https://teest.com",
                },
            )

            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=distinct_id_1,
                timestamp=self.EVENT_TIMESTAMP,
                elements=[Element(nth_of_type=1, nth_child=0, tag_name="a", text="Insight", attr_class=["ant-btn"])],
                properties={
                    "$session_id": session_id,
                    "$host": "teest.com",
                    "mat_$host": "teest.com",
                    "$current_url": "https://teest.com",
                    "mat_$current_url": "https://teest.com",
                },
            )

            # Flush events to ClickHouse
            flush_persons_and_events()

        # Run query with properties that trigger the error
        # Use property filters that should force the any() expression into the WHERE clause
        properties = [
            EventPropertyFilter(key="mat_$host", value="teest.com", operator="exact", type="event"),
            EventPropertyFilter(key="mat_$current_url", value="https://teest.com", operator="icontains", type="event"),
        ]

        results = self._run_web_goals_query(
            date_from="-24h",
            date_to=None,
            properties=properties,
            compare=False,
        )

        assert results is not None
        assert pretty_print_in_tests(str(results.results), self.team.pk) == self.snapshot
