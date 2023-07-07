from uuid import UUID

import pytz
from django.test import override_settings
from django.utils import timezone
from freezegun import freeze_time

from posthog import datetime
from posthog.hogql import ast
from posthog.hogql.errors import SyntaxException
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.models import Cohort
from posthog.models.cohort.util import recalculate_cohortpeople
from posthog.models.utils import UUIDT
from posthog.session_recordings.test.test_factory import create_snapshot
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events


class TestQuery(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

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
                f"SELECT count(), events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s), 0)) GROUP BY events.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT count, event FROM (SELECT count() AS count, events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s), 0)) GROUP BY events.event) GROUP BY count, event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT c.count, c.event FROM (SELECT count(*) AS count, events.event FROM events WHERE and(equals(events.team_id, {self.team.id}), ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_1)s), 0)) GROUP BY events.event) AS c GROUP BY c.count, c.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT DISTINCT persons.properties___sneaky_mail FROM (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___sneaky_mail, argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___random_uuid, person.id AS id FROM person WHERE equals(person.team_id, {self.team.id}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) AS persons WHERE ifNull(equals(persons.properties___random_uuid, %(hogql_val_2)s), 0) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT DISTINCT person_distinct_ids.person_id, person_distinct_ids.distinct_id FROM (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.id}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS person_distinct_ids LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_0)s), pdi.distinct_id, p.id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(p.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '') FROM events AS e LEFT JOIN person_distinct_id2 AS pdi ON equals(pdi.distinct_id, e.distinct_id) LEFT JOIN person AS p ON equals(p.id, pdi.person_id) WHERE and(equals(p.team_id, {self.team.id}), equals(pdi.team_id, {self.team.id}), equals(e.team_id, {self.team.id})) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS pdi ON "
                f"equals(e.distinct_id, pdi.distinct_id) WHERE equals(e.team_id, {self.team.id}) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), events__pdi.distinct_id, events__pdi.person_id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT e.event, toTimeZone(e.timestamp, %(hogql_val_0)s), e__pdi.distinct_id, e__pdi.person_id FROM events AS e INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"argMax(person.created_at, person.version) AS created_at, person.id AS id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, "
                f"person.version), 0), 0)) AS pdi__person ON equals(pdi.person_id, pdi__person.id) WHERE "
                f"equals(pdi.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"AS properties___sneaky_mail, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
                f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) AS pdi__person ON "
                f"equals(pdi.person_id, pdi__person.id) WHERE equals(pdi.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
                f"INNER JOIN (SELECT person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING "
                f"ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) AS events__pdi__person ON "
                f"equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) "
                f"AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT "
                f"argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) "
                f"AS properties___sneaky_mail, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING "
                f"ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) AS events__pdi__person ON equals(events__pdi.person_id, "
                f"events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0), 0)) AS e__pdi ON equals(e.distinct_id, e__pdi.distinct_id) INNER JOIN "
                f"(SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), "
                f"person.version) AS properties___sneaky_mail, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) "
                f"GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) AS e__pdi__person ON "
                f"equals(e__pdi.person_id, e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id "
                f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
                f"HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS e__pdi ON equals(e.distinct_id, "
                f"e__pdi.distinct_id) INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), "
                f"'^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id AS id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) "
                f"AS e__pdi__person ON equals(e__pdi.person_id, e__pdi__person.id) WHERE equals(e.team_id, {self.team.pk}) LIMIT 10"
                f" SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE "
                f"equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
                f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS s__pdi ON "
                f"equals(s.distinct_id, s__pdi.distinct_id) INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, "
                f"%(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id AS id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) "
                f"AS s__pdi__person ON equals(s__pdi.person_id, s__pdi__person.id) WHERE equals(s.team_id, {self.team.pk}) "
                f"GROUP BY s__pdi__person.properties___sneaky_mail LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True"
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
                f" SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
                f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, "
                f"person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
                f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), "
                f"'^\"|\"$', ''), person.version) AS properties___sneaky_mail, person.id AS id FROM person WHERE "
                f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0)) "
                f"AS events__pdi__person ON equals(events__pdi.person_id, events__pdi__person.id) "
                f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT events.event, toTimeZone(events.timestamp, %(hogql_val_0)s), events.person_id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '') FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                    f"SELECT events.event, count() FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(events.team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT cohortpeople.person_id FROM cohortpeople WHERE and(equals(cohortpeople.team_id, {self.team.pk}), equals(cohortpeople.cohort_id, {cohort.pk})) GROUP BY cohortpeople.person_id, cohortpeople.cohort_id, cohortpeople.version HAVING greater(sum(cohortpeople.sign), 0)))) GROUP BY events.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                    f"cohortpeople.version HAVING greater(sum(cohortpeople.sign), 0)))) GROUP BY events.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                    f"SELECT events.event, count() FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) WHERE and(equals(events.team_id, {self.team.pk}), in(events__pdi.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) GROUP BY events.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                    f"SELECT events.event, count(*) FROM events WHERE and(equals(events.team_id, {self.team.pk}), in(events.person_id, (SELECT person_static_cohort.person_id FROM person_static_cohort WHERE and(equals(person_static_cohort.team_id, {self.team.pk}), equals(person_static_cohort.cohort_id, {cohort.pk}))))) GROUP BY events.event LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT e.event, s.session_id FROM events AS e LEFT JOIN session_recording_events AS s ON equals(s.session_id, nullIf(nullIf(e.`$session_id`, ''), 'null')) WHERE and(equals(s.team_id, {self.team.pk}), equals(e.team_id, {self.team.pk}), isNotNull(nullIf(nullIf(e.`$session_id`, ''), 'null'))) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_recording_events s left join events e on e.properties.$session_id = s.session_id where e.properties.$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM session_recording_events AS s LEFT JOIN events AS e ON equals(nullIf(nullIf(e.`$session_id`, ''), 'null'), s.session_id) WHERE and(equals(e.team_id, {self.team.pk}), equals(s.team_id, {self.team.pk}), isNotNull(nullIf(nullIf(e.`$session_id`, ''), 'null'))) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT e.event, s.session_id FROM events AS e LEFT JOIN session_recording_events AS s ON equals(s.session_id, replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')) WHERE and(equals(s.team_id, {self.team.pk}), equals(e.team_id, {self.team.pk}), isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
            )
            self.assertEqual(response.results, [("$pageview", "111"), ("$pageview", "111")])

            response = execute_hogql_query(
                "select e.event, s.session_id from session_recording_events s left join events e on e.properties.$$$session_id = s.session_id where e.properties.$$$session_id is not null limit 10",
                team=self.team,
            )
            self.assertEqual(
                response.clickhouse,
                f"SELECT e.event, s.session_id FROM session_recording_events AS s LEFT JOIN events AS e ON equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), s.session_id) WHERE and(equals(e.team_id, {self.team.pk}), equals(s.team_id, {self.team.pk}), isNotNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(e.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))) LIMIT 10 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SELECT arrayMap(x -> multiply(x, 2), [1, 2, 3]), 1 LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
            )

    def test_hogql_arrays(self):
        with override_settings(PERSON_ON_EVENTS_V2_OVERRIDE=False):
            response = execute_hogql_query(
                "SELECT [1, 2, 3], [10,11,12][1]",
                team=self.team,
            )
            # Following SQL tradition, ClickHouse array indexes start at 1, not from zero.
            self.assertEqual(response.results, [([1, 2, 3], 10)])
            self.assertEqual(
                response.clickhouse,
                f"SELECT [1, 2, 3], [10, 11, 12][1] LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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
                f"SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
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

    def test_window_functions_with_window(self):
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

        query = f"""
           select distinct_id,
                  timestamp,
                  event,
                  groupArray(event) OVER w1 AS two_before,
                  groupArray(event) OVER w2 AS two_after,
                  row_number() OVER w1 AS rn_1,
                  row_number() OVER w2 AS rn_2,
                  first_value(event) OVER w1 AS first_value_1,
                  last_value(event) OVER w1 AS last_value_1,
                  first_value(event) OVER w2 AS first_value_2,
                  last_value(event) OVER w2 AS last_value_2,
                  rank() OVER w1 AS rank_1,
                  dense_rank() OVER w2 AS rank_2
             from events
            where timestamp > toDateTime('2020-01-09 00:00:00')
              and distinct_id like '%_{random_uuid}'
           window w1 as (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING),
                  w2 as (PARTITION BY distinct_id ORDER BY timestamp ASC ROWS BETWEEN 1 FOLLOWING AND 2 FOLLOWING)
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
                    1,
                    1,
                    "",
                    "",
                    "random bla",
                    "random boo",
                    1,
                    1,
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 10, 00, tzinfo=pytz.UTC),
                    "random bla",
                    ["random event"],
                    ["random boo"],
                    2,
                    2,
                    "random event",
                    "random event",
                    "random boo",
                    "random boo",
                    2,
                    2,
                ),
                (
                    f"person_{person}_{random_uuid}",
                    datetime.datetime(2020, 1, 10, 00, 20, 00, tzinfo=pytz.UTC),
                    "random boo",
                    ["random event", "random bla"],
                    [],
                    3,
                    3,
                    "random event",
                    "random bla",
                    "",
                    "",
                    3,
                    3,
                ),
            ]
        self.assertEqual(response.results, expected)

    def test_with_pivot_table_1_level(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                 WITH PIVOT_TABLE_COL_ABC AS (
                             SELECT properties.index as col_a,
                                    event as col_b,
                                    count() as col_c
                               FROM events
                           GROUP BY properties.index,
                                    event
                          ),
                          PIVOT_FUNCTION_1 AS (
                              select col_a, groupArray( (col_b, col_c) ) as g from
                                PIVOT_TABLE_COL_ABC
                                group by col_a
                          ),
                          PIVOT_FUNCTION_2 AS (
                              select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) r from
                              PIVOT_FUNCTION_1
                              group by col_a
                          )
                   SELECT *
                     FROM PIVOT_FUNCTION_2
                 ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
            )
            self.assertEqual(response.results, [("0", [("random event", 1)]), ("1", [("random event", 1)])])
            self.assertEqual(
                response.clickhouse,
                f"SELECT PIVOT_FUNCTION_2.col_a, PIVOT_FUNCTION_2.r FROM "
                f"(SELECT PIVOT_FUNCTION_1.col_a, arrayZip((sumMap(PIVOT_FUNCTION_1.g.1, PIVOT_FUNCTION_1.g.2) AS x).1, x.2) AS r "
                f"FROM (SELECT PIVOT_TABLE_COL_ABC.col_a, groupArray(tuple(PIVOT_TABLE_COL_ABC.col_b, PIVOT_TABLE_COL_ABC.col_c)) AS g "
                f"FROM (SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') "
                f"AS col_a, events.event AS col_b, count() AS col_c FROM events WHERE equals(events.team_id, {self.team.pk}) "
                f"GROUP BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), "
                f"'^\"|\"$', ''), events.event) AS PIVOT_TABLE_COL_ABC GROUP BY PIVOT_TABLE_COL_ABC.col_a) AS PIVOT_FUNCTION_1 "
                f"GROUP BY PIVOT_FUNCTION_1.col_a) AS PIVOT_FUNCTION_2 ORDER BY PIVOT_FUNCTION_2.col_a ASC "
                f"LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
            )

    def test_with_pivot_table_2_levels(self):
        with freeze_time("2020-01-10"):
            self._create_random_events()
            # sample pivot table, testing tuple access
            query = """
                 WITH PIVOT_TABLE_COL_ABC AS (
                             SELECT properties.index as col_a,
                                    event as col_b,
                                    count() as col_c
                               FROM events
                           GROUP BY properties.index,
                                    event
                          ),
                          PIVOT_FUNCTION_1 AS (
                              select col_a, groupArray( (col_b, col_c) ) as g from
                                PIVOT_TABLE_COL_ABC
                                group by col_a
                          ),
                          PIVOT_FUNCTION_2 AS (
                              select col_a, arrayZip( (sumMap( g.1, g.2 ) as x).1, x.2) r from
                              PIVOT_FUNCTION_1
                              group by col_a
                          ),
                          final as (select * from PIVOT_FUNCTION_2)
                   SELECT *
                     FROM final
                 ORDER BY col_a
            """
            response = execute_hogql_query(
                query,
                team=self.team,
            )
            self.assertEqual(response.results, [("0", [("random event", 1)]), ("1", [("random event", 1)])])
            self.assertEqual(
                response.clickhouse,
                f"SELECT final.col_a, final.r FROM (SELECT PIVOT_FUNCTION_2.col_a, PIVOT_FUNCTION_2.r FROM "
                f"(SELECT PIVOT_FUNCTION_1.col_a, arrayZip((sumMap(PIVOT_FUNCTION_1.g.1, PIVOT_FUNCTION_1.g.2) AS x).1, x.2) AS r FROM "
                f"(SELECT PIVOT_TABLE_COL_ABC.col_a, groupArray(tuple(PIVOT_TABLE_COL_ABC.col_b, PIVOT_TABLE_COL_ABC.col_c)) AS g FROM "
                f"(SELECT replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '') AS col_a, "
                f"events.event AS col_b, count() AS col_c FROM events WHERE equals(events.team_id, {self.team.pk}) "
                f"GROUP BY replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), "
                f"events.event) AS PIVOT_TABLE_COL_ABC GROUP BY PIVOT_TABLE_COL_ABC.col_a) AS PIVOT_FUNCTION_1 "
                f"GROUP BY PIVOT_FUNCTION_1.col_a) AS PIVOT_FUNCTION_2) AS final ORDER BY final.col_a ASC LIMIT 100 "
                f"SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=True",
            )

    def test_property_access_with_arrays(self):
        with freeze_time("2020-01-10"):
            random_uuid = str(UUIDT())
            _create_person(team=self.team, distinct_ids=[f"P{random_uuid}"], is_identified=True)
            _create_event(
                distinct_id=f"P{random_uuid}",
                event="big event",
                team=self.team,
                properties={
                    "string": random_uuid,
                    "array_str": [random_uuid],
                    "obj_array": {"id": [random_uuid]},
                    "array_array_str": [[random_uuid]],
                    "array_obj": [{"id": random_uuid}],
                    "array_obj_array": [{"id": [random_uuid]}],
                    "array_obj_array_obj": [{"id": [{"id": random_uuid}]}],
                },
            )
            flush_persons_and_events()

            alternatives = [
                "properties.string",
                "properties.array_str.1",
                "properties.array_str[1]",
                "properties.obj_array.id.1",
                "properties.obj_array.id[1]",
                "properties.array_array_str.1.1",
                "properties.array_array_str[1][1]",
                "properties.array_obj_array.1.id.1",
                "properties.array_obj_array[1]['id'][1]",
                "properties.array_obj_array_obj.1.id.1.id",
                "properties.array_obj_array_obj[1].id[1].id",
                "properties.array_obj_array_obj[1]['id'][1]['id']",
                "properties.array_obj.1.id",
                "properties.array_obj[1].id",
            ]
            columns = ",".join(alternatives)
            query = f"SELECT {columns} FROM events WHERE properties.string = '{random_uuid}'"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results[0], tuple(map(lambda x: random_uuid, alternatives)))

    def test_property_access_with_arrays_zero_index_error(self):
        query = f"SELECT properties.something[0] FROM events"
        with self.assertRaises(SyntaxException) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "SQL indexes start from one, not from zero. E.g: array[1]")

        query = f"SELECT properties.something.0 FROM events"
        with self.assertRaises(SyntaxException) as e:
            execute_hogql_query(query, team=self.team)
        self.assertEqual(str(e.exception), "SQL indexes start from one, not from zero. E.g: array[1]")

    def test_time_window_functions(self):
        query = """
            SELECT
                tumble(toDateTime('2020-01-01'), toIntervalDay('1')),
                tumbleStart(toDateTime('2020-01-01'), toIntervalDay('1')),
                tumbleEnd(toDateTime('2020-01-01'), toIntervalDay('1')),
                hop(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2')),
                hopStart(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2')),
                hopEnd(toDateTime('2020-01-01'), toIntervalDay('1'), toIntervalDay('2'))
        """

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(
            response.results,
            [
                (
                    (
                        datetime.datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
                        datetime.datetime(2020, 1, 2, 0, 0, tzinfo=timezone.utc),
                    ),
                    datetime.datetime(2020, 1, 1, 0, 0, tzinfo=timezone.utc),
                    datetime.datetime(2020, 1, 2, 0, 0, tzinfo=timezone.utc),
                    (
                        datetime.datetime(2019, 12, 31, 0, 0, tzinfo=timezone.utc),
                        datetime.datetime(2020, 1, 2, 0, 0, tzinfo=timezone.utc),
                    ),
                    datetime.datetime(2019, 12, 31, 0, 0, tzinfo=timezone.utc),
                    datetime.datetime(2020, 1, 2, 0, 0, tzinfo=timezone.utc),
                )
            ],
        )

    def test_null_equality(self):
        expected = [
            ("null", "!=", "2", 1),
            ("2", "!=", "null", 1),
            ("3", "!=", "4", 1),
            ("3", "!=", "3", 0),
            ("null", "!=", "null", 0),
            ("null", "=", "2", 0),
            ("2", "=", "null", 0),
            ("3", "=", "4", 0),
            ("3", "=", "3", 1),
            ("null", "=", "null", 1),
        ]

        for (a, op, b, res) in expected:
            # works when selecting directly
            query = f"select {a} {op} {b}"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], query)

            # works when selecting via a subquery
            query = f"select a {op} b from (select {a} as a, {b} as b)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], query)

            # works when selecting via a subquery
            query = f"select {a} {op} b from (select {b} as b)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], query)

            # works when selecting via a subquery
            query = f"select a {op} {b} from (select {a} as a)"
            response = execute_hogql_query(query, team=self.team)
            self.assertEqual(response.results, [(res,)], query)

    def test_regex_functions(self):
        query = """
            SELECT
                'kala' ~ '.*',
                'kala' =~ '.*',
                'kala' !~ '.*',
                'kala' =~ 'a',
                'kala' !~ 'a',
                'kala' =~ 'A',
                'kala' !~ 'A',
                'kala' ~* 'A',
                'kala' =~* 'A',
                'kala' !~* 'A'
        """

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(
            response.results,
            [(True, True, False, True, False, False, True, True, True, False)],
        )

    def test_nullish_coalescing(self):
        query = """
            SELECT
                null ?? 1,
                null ?? null ?? 2,
                3 ?? null,
                null ?? 'string',
                1 + (null ?? 2) + 3,
                1 + null ?? 2 + 3,
                10 ?? true ? 20 : 30,
                10 ?? 5 + 10
        """

        response = execute_hogql_query(
            query,
            team=self.team,
        )

        self.assertEqual(
            response.results,
            [(1, 2, 3, "string", 6, 5, 20, 10)],
        )
