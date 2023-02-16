from freezegun import freeze_time

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.models.utils import UUIDT
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"email": "tim@posthog.com", "random_uuid": random_uuid},
            team=self.team,
            distinct_ids=["bla"],
            is_identified=True,
        )
        flush_persons_and_events()
        for index in range(2):
            _create_event(
                distinct_id="bla",
                event="random event",
                team=self.team,
                properties={"random_prop": "don't include", "random_uuid": random_uuid, "index": index},
            )
        flush_persons_and_events()
        return random_uuid

    def test_query(self):
        with freeze_time("2020-01-10"):
            random_uuid = self._create_random_events()

            response = execute_hogql_query(
                "select count(), event from events where properties.random_uuid = {random_uuid} group by event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
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
                "select count, event from (select count() as count, event from events where properties.random_uuid = {random_uuid} group by event) group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT count, event FROM (SELECT count(*) AS count, event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event) GROUP BY count, event LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event) GROUP BY count, event LIMIT 1000",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select count, event from (select count() as count, event from events where properties.random_uuid = {random_uuid} group by event) as c group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT c.count, c.event FROM (SELECT count(*) AS count, event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event) AS c GROUP BY c.count, c.event LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event) AS c GROUP BY count, event LIMIT 1000",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select distinct properties.email from persons where properties.random_uuid = {random_uuid}",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '') FROM person WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_1)s), '^\"|\"$', ''), %(hogql_val_2)s)) LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT DISTINCT properties.email FROM person WHERE equals(properties.random_uuid, %(hogql_val_3)s) LIMIT 1000",
            )
            self.assertEqual(response.results, [("tim@posthog.com",)])

            response = execute_hogql_query(
                f"select distinct person_id, distinct_id from person_distinct_ids",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.id}) LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT DISTINCT person_id, distinct_id FROM person_distinct_id2 LIMIT 1000",
            )
            self.assertTrue(len(response.results) > 0)

    def test_query_joins_simple(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.email
                FROM events e
                LEFT JOIN person_distinct_ids pdi
                ON pdi.distinct_id = e.distinct_id
                LEFT JOIN persons p
                ON p.id = pdi.person_id
                """,
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, pdi.distinct_id, p.id, replaceRegexpAll(JSONExtractRaw(p.properties, %(hogql_val_0)s), '^\"|\"$', '') FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) WHERE and(equals(p.team_id, {self.team.id}), equals(pdi.team_id, {self.team.id}), equals(e.team_id, {self.team.id})) LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.email FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) LIMIT 1000",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][4], "tim@posthog.com")

    def test_query_joins_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                    SELECT event, timestamp, pdi.person_id from events e
                    INNER JOIN (
                        SELECT distinct_id,
                               argMax(person_id, version) as person_id
                          FROM person_distinct_ids
                         GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                       ) AS pdi
                    ON e.distinct_id = pdi.distinct_id
                    """,
                self.team,
            )

            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_distinct_id2.person_id, version) AS person_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.id}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) WHERE equals(e.team_id, {self.team.id}) LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_id, version) AS person_id FROM person_distinct_id2 GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) LIMIT 1000",
            )
            self.assertTrue(len(response.results) > 0)

    def test_query_joins_pdi_automatic(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10
                """,
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, timestamp, events_pdi.distinct_id, events_pdi.person_id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, 1) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events_pdi ON equals(events.distinct_id, events_pdi.distinct_id) WHERE equals(team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][4], "00000000-0000-4000-8000-000000000001")

    def test_query_joins_person(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                    SELECT event, timestamp, pdi.person_id from events e
                    INNER JOIN (
                        SELECT distinct_id,
                               argMax(person_id, version) as person_id
                          FROM person_distinct_ids
                         GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                       ) AS pdi
                    ON e.distinct_id = pdi.distinct_id
                    INNER JOIN (
                        SELECT id
                          FROM person
                         WHERE team_id = 1
                           AND id IN (
                                SELECT id
                                  FROM person
                                 WHERE team_id = 1
                                   AND (has(['Chrome'], replaceRegexpAll(JSONExtractRaw(person.properties, '$browser'), '^"|"$', '')))
                               )
                         GROUP BY id
                        HAVING max(is_deleted) = 0
                           AND (has(['Chrome'], replaceRegexpAll(JSONExtractRaw(argMax(person.properties, version), '$browser'), '^"|"$', '')))
                       ) person
                    ON person.id = pdi.person_id
                    """,
                self.team,
            )

            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_distinct_id2.person_id, version) AS person_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.id}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) WHERE equals(e.team_id, {self.team.id}) LIMIT 1000",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_id, version) AS person_id FROM person_distinct_id2 GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) LIMIT 1000",
            )
            self.assertTrue(len(response.results) > 0)
