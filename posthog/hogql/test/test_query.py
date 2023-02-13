from freezegun import freeze_time

from posthog.hogql.query import execute_hogql_query
from posthog.models.utils import UUIDT
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def test_query(self):
        with freeze_time("2020-01-10"):
            random_uuid = str(UUIDT())
            for index in range(2):
                _create_event(
                    distinct_id="bla",
                    event="random event",
                    team=self.team,
                    properties={"random_prop": "don't include", "random_uuid": random_uuid, "index": index},
                )
            flush_persons_and_events()

            response = execute_hogql_query(
                f"select count(), event from events where properties.random_uuid = '{random_uuid}' group by event",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT count(*), event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count(), event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event LIMIT 1000",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                f"select count, event from (select count() as count, event from events where properties.random_uuid = '{random_uuid}' group by event) as c group by count, event",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT count, event FROM (SELECT count(*) AS count, event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event) AS c GROUP BY count, event LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event) AS c GROUP BY count, event LIMIT 1000",
            )
            self.assertEqual(response.results, [(2, "random event")])
