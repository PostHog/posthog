from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models import PropertyDefinition
from posthog.test.base import BaseTest


class TestPropertyTypes(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_height",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.EVENT,
            name="$screen_width",
            defaults={"property_type": "Numeric"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team, type=PropertyDefinition.Type.EVENT, name="bool", defaults={"property_type": "Boolean"}
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team, type=PropertyDefinition.Type.PERSON, name="tickets", defaults={"property_type": "Numeric"}
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="provided_timestamp",
            defaults={"property_type": "DateTime"},
        )
        PropertyDefinition.objects.get_or_create(
            team=self.team,
            type=PropertyDefinition.Type.PERSON,
            name="$initial_browser",
            defaults={"property_type": "String"},
        )

    def test_resolve_property_types_event(self):
        printed = self._print_select(
            "select properties.$screen_width * properties.$screen_height, properties.bool from events"
        )
        expected = (
            "SELECT multiply("
            "toFloat64OrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')), "
            "toFloat64OrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''))), "
            "ifNull(equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_2)s), ''), 'null'), '^\"|\"$', ''), %(hogql_val_3)s), 0) "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def test_resolve_property_types_person_raw(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        expected = (
            "SELECT toFloat64OrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')), "
            "parseDateTime64BestEffortOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), 6, %(hogql_val_2)s), "
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_3)s), ''), 'null'), '^\"|\"$', '') "
            f"FROM person WHERE equals(person.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def test_resolve_property_types_person(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        expected = (
            "SELECT toFloat64OrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', '')), "
            "parseDateTime64BestEffortOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', ''), 6, %(hogql_val_2)s), "
            "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_3)s), ''), 'null'), '^\"|\"$', '') "
            f"FROM person WHERE equals(person.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_combined(self):
        printed = self._print_select("select properties.$screen_width * person.properties.tickets from events")
        expected = (
            "SELECT multiply("
            "toFloat64OrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.properties, %(hogql_val_1)s), ''), 'null'), '^\"|\"$', '')), "
            "toFloat64OrNull(events__pdi__person.properties___tickets)) FROM events INNER JOIN "
            "(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 "
            f"WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) AS events__pdi "
            "ON equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT "
            "argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), person.version) AS properties___tickets, "
            f"person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS events__pdi__person "
            f"ON equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_resolve_property_types_event_person_poe_off(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        expected = (
            f"SELECT parseDateTime64BestEffortOrNull(events__pdi__person.properties___provided_timestamp, 6, %(hogql_val_1)s) FROM events "
            f"INNER JOIN (SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, "
            f"person_distinct_id2.distinct_id AS distinct_id FROM person_distinct_id2 WHERE equals(person_distinct_id2.team_id, {self.team.pk}) "
            f"GROUP BY person_distinct_id2.distinct_id HAVING ifNull(equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0), 0)) "
            f"AS events__pdi ON equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT "
            f"argMax(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(person.properties, %(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), "
            f"person.version) AS properties___provided_timestamp, person.id AS id FROM person WHERE equals(person.team_id, {self.team.pk}) "
            f"GROUP BY person.id HAVING ifNull(equals(argMax(person.is_deleted, person.version), 0), 0) SETTINGS optimize_aggregation_in_order=1) AS events__pdi__person ON "
            f"equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=True)
    def test_resolve_property_types_event_person_poe_on(self):
        printed = self._print_select("select person.properties.provided_timestamp from events")
        expected = (
            f"SELECT parseDateTime64BestEffortOrNull(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(events.person_properties, "
            f"%(hogql_val_0)s), ''), 'null'), '^\"|\"$', ''), 6, %(hogql_val_1)s) FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 10000"
        )
        self.assertEqual(printed, expected)

    def _print_select(self, select: str):
        expr = parse_select(select)
        return print_ast(expr, HogQLContext(team_id=self.team.pk, enable_select_queries=True), "clickhouse")
