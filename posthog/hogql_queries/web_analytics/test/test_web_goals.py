from datetime import datetime
from typing import Optional

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.web_goals import WebGoalsQueryRunner
from posthog.models import Action, Person, Element
from posthog.models.utils import uuid7
from posthog.schema import (
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
)


class TestWebGoalsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        person_result = []
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person_result.append(
                    _create_person(
                        team_id=self.team.pk,
                        distinct_ids=[id],
                        properties={
                            "name": id,
                            **({"email": "test@posthog.com"} if id == "test" else {}),
                        },
                    )
                )
            for timestamp, session_id, pathname in timestamps:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={"$session_id": session_id, "$pathname": pathname},
                )
        return person_result

    def _create_person(self):
        distinct_id = str(uuid7())
        return _create_person(
            uuid=distinct_id,
            team_id=self.team.pk,
            distinct_ids=[distinct_id],
            properties={
                "name": distinct_id,
                **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
            },
        )

    def _visit_web_analytics(self, person: Person, session_id: Optional[str] = None):
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=person.uuid,
            properties={
                "$pathname": "/project/2/web",
                "$current_url": "https://us.posthog.com/project/2/web",
                "$session_id": session_id or person.uuid,
            },
        )

    def _click_pay(self, person: Person, session_id: Optional[str] = None):
        _create_event(
            team=self.team,
            event="$autocapture",
            distinct_id=person.uuid,
            elements=[Element(nth_of_type=1, nth_child=0, tag_name="button", text="Pay $10")],
            properties={"$session_id": session_id or person.uuid},
        )

    def _create_actions(self):
        Action.objects.create(
            team=self.team,
            name="Clicked Pay",
            steps_json=[
                {
                    "event": "$autocapture",
                    "tag_name": "button",
                    "text": "Pay $10",
                }
            ],
        )
        Action.objects.create(
            team=self.team,
            name="Contacted Sales",
            steps_json=[
                {
                    "event": "$autocapture",
                    "tag_name": "button",
                    "text": "Contacted Sales",
                }
            ],
            pinned_at=datetime.now(),
        )
        Action.objects.create(
            team=self.team,
            name="Visited Web Analytics",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://(app|eu|us)\\.posthog\\.com/project/\\d+/web.*",
                    "url_matching": "regex",
                }
            ],
        )

    def _run_web_goals_query(
        self,
        date_from,
        date_to,
        limit=None,
        path_cleaning_filters=None,
        properties=None,
        session_table_version: SessionTableVersion = SessionTableVersion.V2,
        filter_test_accounts: Optional[bool] = False,
    ):
        modifiers = HogQLQueryModifiers(sessionTableVersion=session_table_version)
        query = WebGoalsQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            limit=limit,
            filterTestAccounts=filter_test_accounts,
        )
        self.team.path_cleaning_filters = path_cleaning_filters or []
        runner = WebGoalsQueryRunner(team=self.team, query=query, modifiers=modifiers)
        return runner.calculate()

    def test_no_crash_when_no_data_or_actions(self):
        results = self._run_web_goals_query("all", None).results
        assert results == []

    def test_no_crash_when_no_data_and_some_actions(self):
        self._create_actions()
        results = self._run_web_goals_query("all", None).results
        assert results == [
            ["Contacted Sales", 0, 0, None],
            ["Visited Web Analytics", 0, 0, None],
            ["Clicked Pay", 0, 0, None],
        ]

    def test_one_user_one_action(self):
        self._create_actions()
        p1 = self._create_person()
        self._visit_web_analytics(p1)
        results = self._run_web_goals_query("all", None).results
        assert results == [["Contacted Sales", 0, 0, 0], ["Visited Web Analytics", 1, 1, 1], ["Clicked Pay", 0, 0, 0]]

    def test_one_user_two_similar_actions_across_sessions(self):
        self._create_actions()
        p1 = self._create_person()
        self._visit_web_analytics(p1)
        s2 = str(uuid7())
        self._visit_web_analytics(p1, s2)
        results = self._run_web_goals_query("all", None).results
        assert results == [["Contacted Sales", 0, 0, 0], ["Visited Web Analytics", 2, 1, 1], ["Clicked Pay", 0, 0, 0]]

    def test_one_user_two_different_actions(self):
        self._create_actions()
        p1 = self._create_person()
        self._visit_web_analytics(p1)
        self._click_pay(p1)
        results = self._run_web_goals_query("all", None).results
        assert results == [["Contacted Sales", 0, 0, 0], ["Visited Web Analytics", 1, 1, 1], ["Clicked Pay", 1, 1, 1]]

    def test_one_users_one_action_each(self):
        self._create_actions()
        p1 = self._create_person()
        p2 = self._create_person()
        self._visit_web_analytics(p1)
        self._click_pay(p2)
        results = self._run_web_goals_query("all", None).results
        assert results == [
            ["Contacted Sales", 0, 0, 0],
            ["Visited Web Analytics", 1, 1, 0.5],
            ["Clicked Pay", 1, 1, 0.5],
        ]

    def test_many_users_and_actions(self):
        self._create_actions()
        # create some users who visited web analytics
        for _ in range(8):
            p = self._create_person()
            self._visit_web_analytics(p)
        # create some users who clicked pay
        for _ in range(4):
            p = self._create_person()
            self._click_pay(p)
        # create some users who did both
        for _ in range(2):
            p = self._create_person()
            self._visit_web_analytics(p)
            self._click_pay(p)
        # create one user who did both twice
        for _ in range(1):
            p = self._create_person()
            self._visit_web_analytics(p)
            self._visit_web_analytics(p)
            self._click_pay(p)
            self._click_pay(p)

        results = self._run_web_goals_query("all", None).results
        assert results == [
            ["Contacted Sales", 0, 0, 0],
            ["Visited Web Analytics", 12, 11, 11 / 15],
            ["Clicked Pay", 8, 7, 7 / 15],
        ]
