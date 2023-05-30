from uuid import UUID

import pytz
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog import datetime
from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.utils import UUIDT
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    def _create_random_events(self) -> str:
        random_uuid = str(UUIDT())
        _create_person(
            properties={"sneaky_mail": "tim@posthog.com", "random_uuid": random_uuid},
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
                f"SELECT count(), events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                f"SELECT count(), event FROM events WHERE equals(properties.random_uuid, '{random_uuid}') GROUP BY event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select count, event from (select count() as count, event from events where properties.random_uuid = {random_uuid} group by event) group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT count, event FROM (SELECT count() AS count, events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY events.event) GROUP BY count, event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                f"SELECT count, event FROM (SELECT count() AS count, event FROM events WHERE equals(properties.random_uuid, '{random_uuid}') GROUP BY event) GROUP BY count, event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select count, event from (select count(*) as count, event from events where properties.random_uuid = {random_uuid} group by event) as c group by count, event",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT c.count, c.event FROM (SELECT count(*) AS count, events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s)) GROUP BY events.event) AS c GROUP BY c.count, c.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                f"SELECT count, event FROM (SELECT count(*) AS count, event FROM events WHERE equals(properties.random_uuid, '{random_uuid}') GROUP BY event) AS c GROUP BY count, event LIMIT 100",
            )
            self.assertEqual(response.results, [(2, "random event")])

            response = execute_hogql_query(
                "select distinct properties.sneaky_mail from persons where properties.random_uuid = {random_uuid}",
                placeholders={"random_uuid": ast.Constant(value=random_uuid)},
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT persons.properties___sneaky_mail FROM (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___sneaky_mail, argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___random_uuid, person.id FROM person WHERE equals(person.team_id, {self.team.id}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) AS persons WHERE equals(persons.properties___random_uuid, %(hogql_val_2)s) LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                f"SELECT DISTINCT properties.sneaky_mail FROM persons WHERE equals(properties.random_uuid, '{random_uuid}') LIMIT 100",
            )
            self.assertEqual(response.results, [("tim@posthog.com",)])

            response = execute_hogql_query(
                f"select distinct person_id, distinct_id from person_distinct_ids",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT DISTINCT person_distinct_ids.person_id, person_distinct_ids.distinct_id FROM (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.id}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS person_distinct_ids LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT DISTINCT person_id, distinct_id FROM person_distinct_ids LIMIT 100",
            )
            self.assertTrue(len(response.results) > 0)

    def test_query_joins_simple(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                """
                SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.sneaky_mail
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
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_0)s), pdi.distinct_id, p.id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(p.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '') FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) WHERE and(equals(p.team_id, {self.team.id}), equals(pdi.team_id, {self.team.id}), equals(e.team_id, {self.team.id})) LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, p.id, p.properties.sneaky_mail FROM events AS e LEFT JOIN person_distinct_ids AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN persons AS p ON equals(p.id, pdi.person_id) LIMIT 100",
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
                          FROM raw_person_distinct_ids
                         GROUP BY distinct_id
                        HAVING argMax(is_deleted, version) = 0
                       ) AS pdi
                    ON e.distinct_id = pdi.distinct_id
                    """,
                self.team,
            )

            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_0)s), pdi.person_id FROM events AS e INNER JOIN (SELECT person_distinct_id2.distinct_id, "
                f"argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id FROM person_distinct_id2 WHERE "
                f"equals(person_distinct_id2.team_id, {self.team.id}) GROUP BY person_distinct_id2.distinct_id HAVING "
                f"equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS pdi ON "
                f"equals(e.distinct_id, pdi.distinct_id) WHERE equals(e.team_id, {self.team.id}) LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.person_id FROM events AS e INNER JOIN (SELECT distinct_id, argMax(person_id, version) AS person_id FROM raw_person_distinct_ids GROUP BY distinct_id HAVING equals(argMax(is_deleted, version), 0)) AS pdi ON equals(e.distinct_id, pdi.distinct_id) LIMIT 100",
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
                response.clickhouse,
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), events__pdi.distinct_id, events__pdi.person_id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person_id FROM events LIMIT 10",
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
                response.hogql,
                "SELECT event, e.timestamp, e.pdi.distinct_id, pdi.person_id FROM events AS e LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_0)s), e__pdi.distinct_id, e__pdi.person_id FROM events AS e INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
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
                "SELECT pdi.distinct_id, pdi.person.created_at FROM person_distinct_ids AS pdi LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT pdi.distinct_id, toTimeZone(pdi__person.created_at, %(hogql_val_0)s) FROM person_distinct_id2 AS pdi INNER JOIN (SELECT "
                f"argMax(person.created_at, person.version) AS created_at, person.id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, "
                f"person.version), 0)) AS pdi__person ON equals(pdi.person_id, pdi__person.id) WHERE "
                f"equals(pdi.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(response.results[0][0], "bla")
            self.assertEqual(response.results[0][1], datetime.datetime(2020, 1, 10, 0, 0, tzinfo=timezone.utc))

    def test_query_joins_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT pdi.distinct_id, pdi.person.properties.sneaky_mail FROM person_distinct_ids pdi LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.hogql,
                "SELECT pdi.distinct_id, pdi.person.properties.sneaky_mail FROM person_distinct_ids AS pdi LIMIT 10",
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT pdi.distinct_id, pdi__person.properties___sneaky_mail FROM person_distinct_id2 AS pdi INNER JOIN "
                f"(SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) "
                f"AS properties___sneaky_mail, person.id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING equals(argMax(person.is_deleted, person.version), 0)) AS pdi__person ON "
                f"equals(pdi.person_id, pdi__person.id) WHERE equals(pdi.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
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
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), events__pdi.distinct_id, events__pdi__person.id FROM events "
                f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
                f"person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
                f"INNER JOIN (SELECT person.id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING "
                f"equals(argMax(person.is_deleted, person.version), 0)) AS events__pdi__person ON "
                f"equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.id FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], UUID("00000000-0000-4000-8000-000000000000"))

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_query_joins_events_pdi_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_1)s), events__pdi.distinct_id, events__pdi__person.properties___sneaky_mail FROM events "
                f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
                f"person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) "
                f"AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT "
                f"argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) "
                f"AS properties___sneaky_mail, person.id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING "
                f"equals(argMax(person.is_deleted, person.version), 0)) AS events__pdi__person ON equals(events__pdi.person_id, "
                f"events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, pdi.distinct_id, pdi.person.properties.sneaky_mail FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    def test_query_joins_events_pdi_e_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, pdi.distinct_id, e.pdi.person.properties.sneaky_mail FROM events e LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_1)s), e__pdi.distinct_id, e__pdi__person.properties___sneaky_mail FROM events AS e "
                f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
                f"person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) INNER JOIN "
                f"(SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), "
                f"person.version) AS properties___sneaky_mail, person.id FROM person WHERE equals(person.team_id, {self.team.pk}) "
                f"GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) AS e__pdi__person ON "
                f"equals(e__pdi.person_id, e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, e.timestamp, pdi.distinct_id, e.pdi.person.properties.sneaky_mail FROM events AS e LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "bla")
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    def test_query_joins_events_person_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, e.timestamp, e.pdi.person.properties.sneaky_mail FROM events e LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_1)s), e__pdi__person.properties___sneaky_mail FROM events AS e INNER JOIN (SELECT "
                f"argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id "
                f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
                f"HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS e__pdi ON equals(e.distinct_id, "
                f"e__pdi.distinct_id) INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), "
                f"'^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) "
                f"AS e__pdi__person ON equals(e__pdi.person_id, e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, e.timestamp, e.pdi.person.properties.sneaky_mail FROM events AS e LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], "tim@posthog.com")

    def test_query_joins_events_person_properties_in_aggregration(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT s.pdi.person.properties.sneaky_mail, count() FROM events s GROUP BY s.pdi.person.properties.sneaky_mail LIMIT 10",
                self.team,
            )
            expected = (
                f"SELECT s__pdi__person.properties___sneaky_mail, count() FROM events AS s INNER JOIN (SELECT argMax(person_distinct_id2.person_id, "
                f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE "
                f"equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
                f"equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS s__pdi ON "
                f"equals(s.distinct_id, s__pdi.distinct_id) INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, "
                f"%(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) "
                f"AS s__pdi__person ON equals(s__pdi.person_id, s__pdi__person.id) WHERE equals(s.team_id, {self.team.pk}) "
                f"GROUP BY s__pdi__person.properties___sneaky_mail LIMIT 10 SETTINGS readonly=1, max_execution_time=60"
            )
            self.assertEqual(response.clickhouse, expected)
            self.assertEqual(
                response.hogql,
                "SELECT s.pdi.person.properties.sneaky_mail, count() FROM events AS s GROUP BY s.pdi.person.properties.sneaky_mail LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    def test_select_person_on_events(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            response = execute_hogql_query(
                "SELECT poe.properties.sneaky_mail, count() FROM events s GROUP BY poe.properties.sneaky_mail LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(s.person_properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), "
                f"count() FROM events AS s WHERE equals(s.team_id, {self.team.pk}) GROUP BY "
                f"replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(s.person_properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '') LIMIT 10"
                f" SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT poe.properties.sneaky_mail, count() FROM events AS s GROUP BY poe.properties.sneaky_mail LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "tim@posthog.com")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_query_select_person_with_joins_without_poe(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_1)s), events__pdi__person.id, events__pdi__person.properties___sneaky_mail "
                f"FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
                f"person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
                f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), "
                f"'^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) "
                f"AS events__pdi__person ON equals(events__pdi.person_id, events__pdi__person.id) "
                f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], UUID("00000000-0000-4000-8000-000000000000"))
            self.assertEqual(response.results[0][3], "tim@posthog.com")

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True)
    def test_query_select_person_with_poe_without_joins(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()

            response = execute_hogql_query(
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
                self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), events.person_id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '') FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(
                response.hogql,
                "SELECT event, timestamp, person.id, person.properties.sneaky_mail FROM events LIMIT 10",
            )
            self.assertEqual(response.results[0][0], "random event")
            self.assertEqual(response.results[0][2], UUID("00000000-0000-4000-8000-000000000000"))
            self.assertEqual(response.results[0][3], "tim@posthog.com")

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
            with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk}, self.team
                        )
                    },
                )
                self.assertEqual(
                    response.clickhouse,
                    f"SELECT events.event, count() FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(events.team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT cohortpeople.person_id FROM cohortpeople WHERE and(equals(cohortpeople.team_id, {self.team.pk}), equals(cohortpeople.cohort_id, {cohort.pk})) GROUP BY cohortpeople.person_id, cohortpeople.cohort_id, cohortpeople.version HAVING greater(sum(cohortpeople.sign), 0)))) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
                )
                self.assertEqual(response.results, [("$pageview", 2)])

            with override_settings(PERSON_ON_EVENTS_OVERRIDE=True):
                response = execute_hogql_query(
                    "SELECT event, count(*) FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk}, self.team
                        )
                    },
                )
                self.assertEqual(
                    response.clickhouse,
                    f"SELECT events.event, count(*) FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, "
                    f"(SELECT cohortpeople.person_id FROM cohortpeople WHERE and(equals(cohortpeople.team_id, {self.team.pk}), "
                    f"equals(cohortpeople.cohort_id, {cohort.pk})) GROUP BY cohortpeople.person_id, cohortpeople.cohort_id, "
                    f"cohortpeople.version HAVING greater(sum(cohortpeople.sign), 0)))) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
                )
                self.assertEqual(response.results, [("$pageview", 2)])

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

            with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
                response = execute_hogql_query(
                    "SELECT event, count() FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk}, self.team
                        )
                    },
                )
                self.assertEqual(response.results, [("$pageview", 1)])

                self.assertEqual(
                    response.clickhouse,
                    f"SELECT events.event, count() FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(events.team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
                )

            with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=True):
                response = execute_hogql_query(
                    "SELECT event, count(*) FROM events WHERE {cohort_filter} GROUP BY event",
                    team=self.team,
                    placeholders={
                        "cohort_filter": property_to_expr(
                            {"type": "cohort", "key": "id", "value": cohort.pk}, self.team
                        )
                    },
                )
                self.assertEqual(response.results, [("$pageview", 1)])
                self.assertEqual(
                    response.clickhouse,
                    f"SELECT events.event, count(*) FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) GROUP BY events.event LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
                )

    def test_join_with_property_materialized_session_id(self):
        with freeze_time("2020-01-10"):
            _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"$some_prop": "something"})
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$session_id": "111"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$session_id": "111"},
            )
            create_snapshot(distinct_id="some_id", session_id="111", timestamp=timezone.now(), team_id=self.team.pk)

            response = execute_hogql_query(
                "select e.event, s.session_id from events e left join session_recording_events s on s.session_id = e.properties.$session_id where e.properties.$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM events AS e LEFT JOIN session_recording_events AS s ON equals(s.session_id, nullIf(nullIf(e.`$session_id`, ''), 'null')) WHERE and(equals(s.team_id, {self.team.pk}), equals(e.team_id, {self.team.pk}), isNotNull(nullIf(nullIf(e.`$session_id`, ''), 'null'))) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_recording_events s left join events e on e.properties.$session_id = s.session_id where e.properties.$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM session_recording_events AS s LEFT JOIN events AS e ON equals(nullIf(nullIf(e.`$session_id`, ''), 'null'), s.session_id) WHERE and(equals(e.team_id, {self.team.pk}), equals(s.team_id, {self.team.pk}), isNotNull(nullIf(nullIf(e.`$session_id`, ''), 'null'))) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

    def test_join_with_property_not_materialized(self):
        with freeze_time("2020-01-10"):
            _create_person(distinct_ids=["some_id"], team_id=self.team.pk, properties={"$some_prop": "something"})
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$$$session_id": "111"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"attr": "some_val", "$$$session_id": "111"},
            )
            create_snapshot(distinct_id="some_id", session_id="111", timestamp=timezone.now(), team_id=self.team.pk)

            response = execute_hogql_query(
                "select e.event, s.session_id from events e left join session_recording_events s on s.session_id = e.properties.$$$session_id where e.properties.$$$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM events AS e LEFT JOIN session_recording_events AS s ON equals(s.session_id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')) WHERE and(equals(s.team_id, {self.team.pk}), equals(e.team_id, {self.team.pk}), isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_recording_events s left join events e on e.properties.$$$session_id = s.session_id where e.properties.$$$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM session_recording_events AS s LEFT JOIN events AS e ON equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), s.session_id) WHERE and(equals(e.team_id, {self.team.pk}), equals(s.team_id, {self.team.pk}), isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))) LIMIT 10 SETTINGS readonly=1, max_execution_time=60",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

    def test_hogql_lambdas(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            response = execute_hogql_query(
                "SELECT arrayMap(x -> x * 2, [1, 2, 3]), 1",
                team=self.team,
            )
            self.assertEqual(response.results, [([2, 4, 6], 1)])
            self.assertEqual(
                response.clickhouse,
                f"SELECT arrayMap(x -> multiply(x, 2), [1, 2, 3]), 1 LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )

    def test_hogql_arrays(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            response = execute_hogql_query(
                "SELECT [1, 2, 3], [10,11,12][1]",
                team=self.team,
            )
            # Following SQL tradition, ClickHouse array indexes start at 1, not 0.
            self.assertEqual(response.results, [([1, 2, 3], 10)])
            self.assertEqual(
                response.clickhouse,
                f"SELECT [1, 2, 3], [10, 11, 12][1] LIMIT 100 SETTINGS readonly=1, max_execution_time=60",
            )

    def test_tuple_access(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) r from (
                select col_a, groupArray( (col_b, col_c) ) as g from
                (
                    SELECT properties.index as col_a,
                           event as col_b,
                           count() as col_c
                      FROM events
                  GROUP BY properties.index,
                           event
                )
                group by col_a)
                group by col_a ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
            )
            self.assertEqual(response.results, [("0", [("random event", 1)]), ("1", [("random event", 1)])])
            self.assertEqual(
                response.clickhouse,
                f"SELECT col_a, arrayZip((sumMap(g.1, g.2) AS x).1, x.2) AS r FROM "
                f"(SELECT col_a, groupArray(tuple(col_b, col_c)) AS g FROM "
                f"(SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') AS col_a, "
                f"events.event AS col_b, count() AS col_c FROM events WHERE equals(events.team_id, {self.team.pk}) "
                f"GROUP BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), events.event) "
                f"GROUP BY col_a) "
                f"GROUP BY col_a ORDER BY col_a ASC LIMIT 100 "
                f"SETTINGS readonly=1, max_execution_time=60",
            )

    def test_null_properties(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            _create_event(
                distinct_id="bla",
                event="empty event",
                team=self.team,
                properties={"empty_string": "", "null": None, "str_zero": "0", "num_zero": 0},
            )

            query = """
                SELECT
                    properties.empty_string,
                    properties.`null`,
                    properties.undefined,
                    properties.str_zero,
                    properties.num_zero
                FROM events
                WHERE events.event='empty event'
            """
            response = execute_hogql_query(
                query,
                team=self.team,
            )
            self.assertEqual(
                response.results,
                [
                    (
                        "",  # empty string
                        None,  # null
                        None,  # undefined
                        "0",  # zero string
                        "0",  # zero number (not typecast)
                    )
                ],
            )

    def test_window_functions_simple(self):
        random_uuid = str(UUIDT())
        for person in range(5):
            distinct_id = f"person_{person}_{random_uuid}"
            with freeze_time("2020-01-10 00:00:00"):
                _create_person(
                    properties={"name": f"Person {person}", "random_uuid": random_uuid},
                    team=self.team,
                    distinct_ids=[distinct_id],
                    is_identified=True,
                )
                _create_event(
                    distinct_id=distinct_id,
                    event="random event",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:10:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random bla",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()
            with freeze_time("2020-01-10 00:20:00"):
                _create_event(
                    distinct_id=distinct_id,
                    event="random boo",
                    team=self.team,
                    properties={"character": "Luigi"},
                )
                flush_persons_and_events()

        # sample funnel table, testing window functions
        query = f"""
           select distinct_id,
                  timestamp,
                  event,
                  groupArray(event) OVER (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING) AS two_before,
                  groupArray(event) OVER (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 1 FOLLOWING AND 2 FOLLOWING) AS two_after
             from events
            where timestamp > toDateTime('2020-01-09 00:00:00')
              and distinct_id like '%_{random_uuid}'
         order by distinct_id, timestamp
        """
        response = execute_hogql_query(query, team=self.team)

        expected = []
        for person in range(5):
            expected += [
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 00, 00, tzinfo=pytz.UTC),
                    "random event",
                    [],
                    ["random bla", "random boo"],
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 10, 00, tzinfo=pytz.UTC),
                    "random bla",
                    ["random event"],
                    ["random boo"],
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 20, 00, tzinfo=pytz.UTC),
                    "random boo",
                    ["random event", "random bla"],
                    [],
                ),
            ]
        self.assertEqual(response.results, expected)

    def test_window_functions_complex_funnel(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample funnel table, testing window functions

        query = """
        SELECT countIf(steps = 1) step_1,
               countIf(steps = 2) step_2,
               countIf(steps = 3) step_3,
               avg(step_1_average_conversion_time_inner) step_1_average_conversion_time,
               avg(step_2_average_conversion_time_inner) step_2_average_conversion_time,
               median(step_1_median_conversion_time_inner) step_1_median_conversion_time,
               median(step_2_median_conversion_time_inner) step_2_median_conversion_time
          FROM (
                SELECT aggregation_target,
                       steps,
                       avg(step_1_conversion_time) step_1_average_conversion_time_inner,
                       avg(step_2_conversion_time) step_2_average_conversion_time_inner,
                       median(step_1_conversion_time) step_1_median_conversion_time_inner,
                       median(step_2_conversion_time) step_2_median_conversion_time_inner
                  FROM (
                        SELECT aggregation_target,
                               steps,
                               max(steps) over (PARTITION BY aggregation_target) as max_steps,
                               step_1_conversion_time,
                               step_2_conversion_time
                          FROM (
                                SELECT *,
                                       if(latest_0 < latest_1 AND latest_1 <= latest_0 + INTERVAL 14 DAY AND latest_1 <= latest_2 AND latest_2 <= latest_0 + INTERVAL 14 DAY, 3, if(latest_0 < latest_1 AND latest_1 <= latest_0 + INTERVAL 14 DAY, 2, 1)) AS steps ,
                                       if(isNotNull(latest_1) AND latest_1 <= latest_0 + INTERVAL 14 DAY, dateDiff('second', latest_0, latest_1), NULL) step_1_conversion_time,
                                       if(isNotNull(latest_2) AND latest_2 <= latest_1 + INTERVAL 14 DAY, dateDiff('second', latest_1, latest_2), NULL) step_2_conversion_time
                                  FROM (
                                        SELECT aggregation_target,
                                               timestamp,
                                               step_0,
                                               latest_0,
                                               step_1,
                                               latest_1,
                                               step_2,
                                               min(latest_2) over (PARTITION by aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) latest_2
                                          FROM (
                                                SELECT aggregation_target,
                                                       timestamp,
                                                       step_0,
                                                       latest_0,
                                                       step_1,
                                                       latest_1,
                                                       step_2,
                                                       if(latest_2 < latest_1, NULL, latest_2) as latest_2
                                                  FROM (
                                                        SELECT aggregation_target,
                                                               timestamp,
                                                               step_0,
                                                               latest_0,
                                                               step_1,
                                                               min(latest_1) over (PARTITION by aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) latest_1,
                                                               step_2,
                                                               min(latest_2) over (PARTITION by aggregation_target ORDER BY timestamp DESC ROWS BETWEEN UNBOUNDED PRECEDING AND 0 PRECEDING) latest_2
                                                          FROM (
                                                                SELECT e.timestamp as timestamp,
                                                                       e.person.id as aggregation_target,
                                                                       e.person.id as person_id ,
                                                                       if(event = '$pageview', 1, 0) as step_0,
                                                                       if(step_0 = 1, timestamp, null) as latest_0,
                                                                       if(event = '$pageview', 1, 0) as step_1,
                                                                       if(step_1 = 1, timestamp, null) as latest_1,
                                                                       if(event = '$autocapture', 1, 0) as step_2,
                                                                       if(step_2 = 1, timestamp, null) as latest_2
                                                                  FROM events e
                                                                 WHERE event IN ['$autocapture', '$pageview']
                                                                   AND timestamp >= toDateTime('2020-01-05 00:00:00')
                                                                   AND timestamp <= toDateTime('2020-01-15 23:59:59')
                                                                   AND (step_0 = 1 OR step_1 = 1 OR step_2 = 1)
                                                               )
                                                       )
                                               )
                                       )
                                 WHERE step_0 = 1
                               )
                       )
                 GROUP BY aggregation_target,
                          steps
                HAVING steps = max_steps
               )
        """
        response = execute_hogql_query(
            query,
            team=self.team,
        )
        self.assertEqual(response.results, [(0, 0, 0, None, None, None, None)])
