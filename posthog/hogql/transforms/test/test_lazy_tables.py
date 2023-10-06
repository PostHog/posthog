from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.test.base import BaseTest


class TestLazyJoins(BaseTest):
    maxDiff = None

    def test_resolve_lazy_tables(self):
        printed = self._print_select("select event, pdi.person_id from events")
        expected = (
            "SELECT events.event, events__pdi.person_id "
            "FROM events "
            "INNER JOIN "
            "(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id "
            f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
            "HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi "
            "ON equals(events.distinct_id, events__pdi.distinct_id) "
            f"WHERE equals(events.team_id, {self.team.pk}) "
            "LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_traversed_fields(self):
        printed = self._print_select("select event, person_id from events")
        expected = (
            f"SELECT events.event, events__pdi.person_id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, "
            f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE "
            f"equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
            f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi "
            f"ON equals(events.distinct_id, events__pdi.distinct_id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def test_resolve_lazy_tables_two_levels(self):
        printed = self._print_select("select event, pdi.person.id from events")
        expected = (
            f"SELECT events.event, events__pdi__person.id FROM events INNER JOIN (SELECT "
            f"argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id "
            f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
            f"HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi ON "
            f"equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT person.id AS id FROM person WHERE "
            f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) "
            f"AS events__pdi__person ON equals(events__pdi.person_id, events__pdi__person.id) "
            f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_traversed(self):
        printed = self._print_select("select event, person.id from events")
        expected = (
            f"SELECT events.event, events__pdi__person.id FROM events INNER JOIN (SELECT argMax(person_distinct_id2.person_id, "
            f"person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE "
            f"equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING "
            f"ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi ON "
            f"equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT person.id AS id FROM person WHERE "
            f"equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) "
            f"AS events__pdi__person ON equals(events__pdi.person_id, events__pdi__person.id) "
            f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties(self):
        printed = self._print_select("select person.properties.$browser from person_distinct_ids")
        expected = (
            f"SELECT person_distinct_ids__person.`properties___$browser` FROM "
            f"(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id "
            f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
            f"HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS person_distinct_ids "
            f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) "
            f"AS `properties___$browser`, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
            f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS person_distinct_ids__person "
            f"ON equals(person_distinct_ids.person_id, person_distinct_ids__person.id) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_one_level_properties_deep(self):
        printed = self._print_select("select person.properties.$browser.in.json from person_distinct_ids")
        expected = (
            f"SELECT person_distinct_ids__person.`properties___$browser___in___json` FROM "
            f"(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id "
            f"FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id "
            f"HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS person_distinct_ids "
            f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s), ''), 'null'), '^\"|\"$', ''), person.version) "
            f"AS `properties___$browser___in___json`, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
            f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS person_distinct_ids__person "
            f"ON equals(person_distinct_ids.person_id, person_distinct_ids__person.id) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def test_resolve_lazy_tables_two_levels_properties(self):
        printed = self._print_select("select event, pdi.person.properties.$browser from events")
        expected = (
            f"SELECT events.event, events__pdi__person.`properties___$browser` FROM events INNER JOIN "
            f"(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
            f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
            f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, "
            f"person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
            f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', "
            f"''), person.version) AS `properties___$browser`, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) "
            f"GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS events__pdi__person "
            f"ON equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_tables_two_levels_properties_duplicate(self):
        printed = self._print_select("select event, person.properties, person.properties.name from events")
        expected = (
            f"SELECT events.event, events__pdi__person.properties, events__pdi__person.properties___name FROM events "
            f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
            f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
            f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, "
            f"person_distinct_id2.version), 0), 0)) AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) "
            f"INNER JOIN (SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) "
            f"AS properties___name, argMax(person.properties, person.version) AS properties, person.id AS id FROM person "
            f"WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) "
            f"AS events__pdi__person ON equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_select_table(self):
        printed = self._print_select("select id, properties.email, properties.$browser from persons")
        expected = (
            f"SELECT persons.id, persons.properties___email, persons.`properties___$browser` FROM "
            f"(SELECT argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS "
            f"properties___email, argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), person.version) "
            f"AS `properties___$browser`, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
            f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS persons LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_lazy_table_as_table_in_join(self):
        printed = self._print_select(
            "select event, distinct_id, events.person_id, persons.properties.email from events left join persons on persons.id = events.person_id limit 10"
        )
        expected = (
            f"SELECT events.event, events.distinct_id, events__pdi.person_id, persons.properties___email FROM events "
            f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
            f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
            f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) "
            f"AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) LEFT JOIN (SELECT "
            f"argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___email, "
            f"person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id "
            f"HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS persons ON equals(persons.id, events__pdi.person_id) "
            f"WHERE equals(events.team_id, {self.team.pk}) LIMIT 10"
        )
        self.assertEqual(printed, expected)

    def test_select_count_from_lazy_table(self):
        printed = self._print_select("select count() from persons")
        expected = (
            f"SELECT count() FROM (SELECT person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) "
            f"GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS persons LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def _print_select(self, select: str):
        expr = parse_select(select)
        return print_ast(expr, HogQLContext(team_id=self.team.pk, enable_select_queries=True), "clickhouse")
