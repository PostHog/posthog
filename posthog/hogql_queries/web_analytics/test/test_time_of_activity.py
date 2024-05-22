from freezegun import freeze_time

from posthog.hogql_queries.web_analytics.time_of_activity import WebTimeOfActivityQueryRunner
from posthog.schema import DateRange, WebTimeOfActivityQuery
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
)


class TestTimeOfActivityQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

    def _run_time_of_activity_query(
        self,
        date_from,
        date_to,
        properties=None,
    ):
        query = WebTimeOfActivityQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
        )

        runner = WebTimeOfActivityQueryRunner(team=self.team, query=query)
        return runner.calculate()

    def test_no_crash_when_no_data(self):
        results = self._run_time_of_activity_query("2023-12-08", "2023-12-15").results
        self.assertEqual({}, results)

    def test_one_session(self):
        self._create_events(
            [
                (
                    "test",
                    [
                        ("2023-12-09T12:34", "session1", "/"),
                        ("2023-12-09T12:56", "session1", "/"),
                        ("2023-12-09T13:37", "session1", "/"),
                    ],
                )
            ]
        )
        results = self._run_time_of_activity_query("2023-12-08", "2023-12-15").results
        self.assertEqual({"saturday": {12: 2, 13: 1}}, results)
