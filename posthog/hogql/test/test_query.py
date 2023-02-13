from freezegun import freeze_time

from posthog.hogql.query import execute_hogql_query
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def test_query(self):
        with freeze_time("2020-01-10"):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "don't include", "some other prop": "with some text"},
            )
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "don't include", "some other prop": "with some text"},
            )
            flush_persons_and_events()
            response = execute_hogql_query("select count(), event from events group by event", self.team)

            response = execute_hogql_query(
                "select c.count, event from (select count() as count, event from events) as c group by count, event",
                self.team,
            )

            self.assertEqual(
                response.clickhouse,
                "SELECT count(*), e0.event FROM events e0 WHERE equals(e0.team_id, 1) GROUP BY e0.event LIMIT 1000",
            )
            self.assertEqual(response.hogql, "SELECT count(), event FROM events e0 GROUP BY event")
            self.assertEqual(response.results, [(2, "random event")])
            # self.assertEqual(response.types, [])
