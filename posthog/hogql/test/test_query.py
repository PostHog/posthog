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
            self.assertEqual(response.results, [(2, "random event")])
