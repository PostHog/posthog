from datetime import datetime
from typing import Optional

from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.web_goals import WebGoalsQueryRunner
from posthog.models import Action
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

    def _create_pageviews(self, distinct_id: str, list_path_time_scroll: list[tuple[str, str, float]]):
        person_time = list_path_time_scroll[0][1]
        with freeze_time(person_time):
            person_result = _create_person(
                team_id=self.team.pk,
                distinct_ids=[distinct_id],
                properties={
                    "name": distinct_id,
                    **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
                },
            )
            session_id = str(uuid7(person_time))
            prev_path_time_scroll = None
            for path_time_scroll in list_path_time_scroll:
                pathname, time, scroll = path_time_scroll
                prev_pathname, _, prev_scroll = prev_path_time_scroll or (None, None, None)
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=distinct_id,
                    timestamp=time,
                    properties={
                        "$session_id": session_id,
                        "$pathname": pathname,
                        "$current_url": "http://www.example.com" + pathname,
                        "$prev_pageview_pathname": prev_pathname,
                        "$prev_pageview_max_scroll_percentage": prev_scroll,
                        "$prev_pageview_max_content_percentage": prev_scroll,
                    },
                )
                prev_path_time_scroll = path_time_scroll
            if prev_path_time_scroll:
                prev_pathname, _, prev_scroll = prev_path_time_scroll
                _create_event(
                    team=self.team,
                    event="$pageleave",
                    distinct_id=distinct_id,
                    timestamp=prev_path_time_scroll[1],
                    properties={
                        "$session_id": session_id,
                        "$pathname": prev_pathname,
                        "$current_url": "http://www.example.com" + pathname,
                        "$prev_pageview_pathname": prev_pathname,
                        "$prev_pageview_max_scroll_percentage": prev_scroll,
                        "$prev_pageview_max_content_percentage": prev_scroll,
                    },
                )
        return person_result

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
            name="Visited Login",
            steps_json=[{"event": "$pageview", "url": "login", "url_matching": "contains"}],
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
        results = self._run_web_goals_query("2023-12-08", "2023-12-15").results
        assert results == []

    def test_no_crash_when_no_data_and_some_actions(self):
        self._create_actions()
        results = self._run_web_goals_query("2023-12-08", "2023-12-15").results
        assert results == [["Contacted Sales", 0, 0, None], ["Visited Login", 0, 0, None], ["Clicked Pay", 0, 0, None]]
