from uuid import UUID

from freezegun import freeze_time

from posthog import datetime
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
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
                f"SELECT count(*), event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count(), event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select count, event from (select count() as count, event from events where properties.random_uuid = {random_uuid} group by event) group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT count, event FROM (SELECT count(*) AS count, event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event) GROUP BY count, event LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event) GROUP BY count, event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select count, event from (select count() as count, event from events where properties.random_uuid = {random_uuid} group by event) as c group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT c.count, c.event FROM (SELECT count(*) AS count, event FROM events WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY event) AS c GROUP BY c.count, c.event LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, %(hogql_val_2)s) GROUP BY event) AS c GROUP BY count, event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select distinct properties.email from persons where properties.random_uuid = {random_uuid}",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', '') FROM person WHERE and(equals(team_id, {self.team.id}), equals(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_1)s), '^\"|\"$', ''), %(hogql_val_2)s)) LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT DISTINCT properties.email FROM person WHERE equals(properties.random_uuid, %(hogql_val_3)s) LIMIT 100",
            )
            self.assertEqual(response.results, [("tim@posthog.com",)])

            response = execute_hogql_query(
                f"select distinct person_id, distinct_id from person_distinct_ids",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.id}) LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT DISTINCT person_id, distinct_id FROM person_distinct_id2 LIMIT 100",
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
                f"SELECT e.event, e.timestamp, pdi.distinct_id, p.id, replaceRegexpAll(JSONExtractRaw(p.properties, %(hogql_val_0)s), '^\"|\"$', '') FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) WHERE and(equals(p.team_id, {self.team.id}), equals(pdi.team_id, {self.team.id}), equals(e.team_id, {self.team.id})) LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.email FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) LIMIT 100",
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
                f"SELECT e.event, e.timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_distinct_id2.person_id, version) AS person_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.id}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) WHERE equals(e.team_id, {self.team.id}) LIMIT 100",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_id, version) AS person_id FROM person_distinct_id2 GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) LIMIT 100",
            )
            self.assertTrue(len(response.results) > 0)

    def test_query_joins_events_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, timestamp, events__pdi.distinct_id, events__pdi.person_id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE equals(team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    def test_query_joins_events_e_pdi(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, e.pdi.distinct_id, pdi.person_id FROM events e LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.hogql, "SELECT event, e.timestamp, e.pdi.distinct_id, pdi.person_id FROM events AS e LIMIT 10"
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, e__pdi.distinct_id, e__pdi.person_id FROM events AS e INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    def test_query_joins_pdi_persons(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT pdi.distinct_id, pdi.person.created_at FROM person_distinct_ids pdi LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.hogql,
                # TODO: store original db name in hogql
                "SELECT pdi.distinct_id, pdi.person.created_at FROM person_distinct_id2 AS pdi LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT pdi.distinct_id, pdi__person.created_at FROM person_distinct_id2 AS pdi INNER JOIN (SELECT argMax(person.created_at, version) AS created_at, id FROM person WHERE equals(team_id, {self.team.pk}) GROUP BY id HAVING equals(argMax(is_deleted, version), 0)) AS pdi__person ON equals(pdi.person_id, pdi__person.id) WHERE equals(pdi.team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "bla")
            self.assertEqual(response.results[0][1], datetime.datetime(2020, 1, 10, 0, 0))

    def test_query_joins_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT pdi.distinct_id, pdi.person.properties.email FROM person_distinct_ids pdi LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.hogql,
                # TODO: store original db name in hogql
                "SELECT pdi.distinct_id, pdi.person.properties.email FROM person_distinct_id2 AS pdi LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT pdi.distinct_id, pdi__person.properties___email FROM person_distinct_id2 AS pdi INNER JOIN "
                f"(SELECT argMax(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), version) "
                f"AS properties___email, id FROM person WHERE equals(team_id, {self.team.pk}) GROUP BY id HAVING "
                f"equals(argMax(is_deleted, version), 0)) AS pdi__person ON equals(pdi.person_id, pdi__person.id) "
                f"WHERE equals(pdi.team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "bla")
            self.assertEqual(response.results[0][1], "tim@posthog.com")

    def test_query_joins_events_pdi_person(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.id FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, timestamp, events__pdi.distinct_id, events__pdi__person.id FROM events "
                f"INNER JOIN (SELECT "
                f"argMax(person_distinct_id2.person_id, version) AS person_id, "
                f"distinct_id "
                f"FROM person_distinct_id2 "
                f"WHERE equals(team_id, {self.team.pk}) "
                f"GROUP BY distinct_id "
                f"HAVING equals(argMax(is_deleted, version), 0)"
                f") AS events__pdi "
                f"ON equals(events.distinct_id, events__pdi.distinct_id) "
                f"INNER JOIN ("
                f"SELECT id "
                f"FROM person "
                f"WHERE equals(team_id, {self.team.pk}) "
                f"GROUP BY id "
                f"HAVING equals(argMax(is_deleted, version), 0)"
                f") AS events__pdi__person "
                f"ON equals(events__pdi.person_id, events__pdi__person.id) "
                f"WHERE equals(team_id, {self.team.pk}) "
                f"LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.id FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    def test_query_joins_events_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.properties.email FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, timestamp, events__pdi.distinct_id, events__pdi__person.properties___email "
                f"FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id "
                f"FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING "
                f"equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, "
                f"events__pdi.distinct_id) INNER JOIN (SELECT argMax(replaceRegexpAll(JSONExtractRaw(properties, "
                f"%(hogql_val_0)s), '^\"|\"$', ''), version) AS properties___email, id FROM person WHERE equals(team_id, "
                f"{self.team.pk}) GROUP BY id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi__person ON "
                f"equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.properties.email FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    def test_query_joins_events_pdi_e_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, pdi.distinct_id, e.pdi.person.properties.email FROM events e LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, e__pdi.distinct_id, e__pdi__person.properties___email "
                f"FROM events AS e INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, "
                f"distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id "
                f"HAVING equals(argMax(is_deleted, version), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) "
                f"INNER JOIN (SELECT argMax(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), "
                f"version) AS properties___email, id FROM person WHERE equals(team_id, {self.team.pk}) GROUP BY id "
                f"HAVING equals(argMax(is_deleted, version), 0)) AS e__pdi__person ON equals(e__pdi.person_id, "
                f"e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, e.timestamp, pdi.distinct_id, e.pdi.person.properties.email FROM events AS e LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    def test_query_joins_events_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, e.pdi.person.properties.email FROM events e LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, e.timestamp, e__pdi__person.properties___email FROM events AS e INNER JOIN (SELECT "
                f"argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 "
                f"WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) "
                f"AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) INNER JOIN (SELECT "
                f"argMax(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), version) "
                f"AS properties___email, id FROM person WHERE equals(team_id, {self.team.pk}) GROUP BY id HAVING "
                f"equals(argMax(is_deleted, version), 0)) AS e__pdi__person ON equals(e__pdi.person_id, "
                f"e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, e.timestamp, e.pdi.person.properties.email FROM events AS e LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "tim@posthog.com")

    def test_query_joins_events_person_properties_in_aggregration(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT s.pdi.person.properties.email, count() FROM events s GROUP BY s.pdi.person.properties.email LIMIT 10",
                self.team,
            )
            expected = (
                "SELECT s__pdi__person.properties___email, count(*) "
                "FROM events AS s "
                "INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id "
                f"FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) "
                "GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) "
                "AS s__pdi ON equals(s.distinct_id, s__pdi.distinct_id) "
                "INNER JOIN (SELECT argMax(replaceRegexpAll(JSONExtractRaw(properties, %(hogql_val_0)s), '^\"|\"$', ''), version) "
                "AS properties___email, id FROM person "
                f"WHERE equals(team_id, {self.team.pk}) GROUP BY id HAVING equals(argMax(is_deleted, version), 0)) "
                "AS s__pdi__person ON equals(s__pdi.person_id, s__pdi__person.id) "
                f"WHERE equals(s.team_id, {self.team.pk}) GROUP BY s__pdi__person.properties___email "
                "LIMIT 10"
            )
            self.assertEqual(response.clickhouse, expected)
            self.assertEqual(
                response.hogql,
                "SELECT s.pdi.person.properties.email, count() FROM events AS s GROUP BY s.pdi.person.properties.email LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    def test_select_person_on_events(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT poe.properties.email, count() FROM events s GROUP BY poe.properties.email LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT replaceRegexpAll(JSONExtractRaw(s.person_properties, %(hogql_val_0)s), '^\"|\"$', ''), "
                f"count(*) FROM events AS s WHERE equals(s.team_id, {self.team.pk}) GROUP BY "
                f"replaceRegexpAll(JSONExtractRaw(s.person_properties, %(hogql_val_1)s), '^\"|\"$', '') LIMIT 10",
            )
            self.assertEqual(
                response.hogql,
                "SELECT poe.properties.email, count() FROM events AS s GROUP BY poe.properties.email LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    def test_prop_cohort_basic(self):
        with freeze_time("2020-01-10"):
            _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
            _create_event(event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"})
            _create_event(
                event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"}
            )
            cohort = Cohort.objects.create(
                team=self.team,
                groups=[{"properties": [{"key": "$some_prop", "value": "something", "type": "person"}]}],
                name="cohort",
            )
            recalculate_cohortpeople(cohort, pending_version=0)
            response = execute_hogql_query(
                "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                team=self.team,
                placeholders={
                    "cohort_filter": property_to_expr({"type": "cohort", "key": "id", "value": cohort.pk}, self.team)
                },
            )
            self.assertEqual(response.results, [("$pageview", 2)])
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, count(*) FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT person_id FROM cohortpeople WHERE and(equals(team_id, {self.team.pk}), equals(cohort_id, {cohort.pk})) GROUP BY person_id, cohort_id, version HAVING greater(sum(sign), 0)))) GROUP BY event LIMIT 100",
            )

    def test_prop_cohort_static(self):
        with freeze_time("2020-01-10"):
            _create_person(distinct_ids=["some_other_id"], team_id=self.team.pk, properties={"$some_prop": "something"})
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_person(distinct_ids=["no_match"], team_id=self.team.pk)
            _create_event(event="$pageview", team=self.team, distinct_id="some_id", properties={"attr": "some_val"})
            _create_event(
                event="$pageview", team=self.team, distinct_id="some_other_id", properties={"attr": "some_val"}
            )
            cohort = Cohort.objects.create(team=self.team, groups=[], is_static=True)
            cohort.insert_users_by_list(["some_id"])
            response = execute_hogql_query(
                "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                team=self.team,
                placeholders={
                    "cohort_filter": property_to_expr({"type": "cohort", "key": "id", "value": cohort.pk}, self.team)
                },
            )
            self.assertEqual(response.results, [("$pageview", 1)])
            self.assertEqual(
                response.clickhouse,
                f"SELECT event, count(*) FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, version) AS person_id, distinct_id FROM person_distinct_id2 WHERE equals(team_id, {self.team.pk}) GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT person_id FROM person_static_cohort WHERE and(equals(team_id, {self.team.pk}), equals(cohort_id, {cohort.pk}))))) GROUP BY event LIMIT 100",
            )
