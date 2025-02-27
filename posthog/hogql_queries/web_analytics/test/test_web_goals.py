from typing import Optional


from posthog.hogql_queries.web_analytics.web_goals import WebGoalsQueryRunner
from posthog.models import Action, Person, Element
from posthog.models.utils import uuid7
from posthog.schema import (
    CompareFilter,
    DateRange,
    SessionTableVersion,
    HogQLQueryModifiers,
    WebGoalsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from freezegun.api import freeze_time


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
