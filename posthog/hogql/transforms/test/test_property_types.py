from django.test import override_settings

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.models import PropertyDefinition, DataBeachTable, DataBeachField, DataBeachFieldType, DataBeachTableEngine
from posthog.test.base import BaseTest


class TestPropertyTypes(BaseTest):
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
            "toFloat64OrNull(replaceRegexpAll(JSONExtractRaw(events.properties, %(hogql_val_0)s), '^\"|\"$', '')), "
            "toFloat64OrNull(replaceRegexpAll(JSONExtractRaw(events.properties, %(hogql_val_1)s), '^\"|\"$', ''))), "
            "equals(replaceRegexpAll(JSONExtractRaw(events.properties, %(hogql_val_2)s), '^\"|\"$', ''), true) "
            f"FROM events WHERE equals(events.team_id, {self.team.pk}) LIMIT 65535"
        )
        self.assertEqual(printed, expected)

    def test_resolve_property_types_person_raw(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        expected = (
            "SELECT toFloat64OrNull(replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_0)s), '^\"|\"$', '')), "
            "parseDateTimeBestEffort(replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_1)s), '^\"|\"$', '')), "
            "replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_2)s), '^\"|\"$', '') "
            f"FROM person WHERE equals(person.team_id, {self.team.pk}) LIMIT 65535"
        )
        self.assertEqual(printed, expected)

    def test_resolve_property_types_person(self):
        printed = self._print_select(
            "select properties.tickets, properties.provided_timestamp, properties.$initial_browser from raw_persons"
        )
        expected = (
            "SELECT toFloat64OrNull(replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_0)s), '^\"|\"$', '')), "
            "parseDateTimeBestEffort(replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_1)s), '^\"|\"$', '')), "
            "replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_2)s), '^\"|\"$', '') "
            f"FROM person WHERE equals(person.team_id, {self.team.pk}) LIMIT 65535"
        )
        self.assertEqual(printed, expected)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=False)
    def test_resolve_property_types_combined(self):
        printed = self._print_select("select properties.$screen_width * person.properties.tickets from events")
        expected = (
            "SELECT multiply("
            "toFloat64OrNull(replaceRegexpAll(JSONExtractRaw(events.properties, %(hogql_val_1)s), '^\"|\"$', '')), "
            "toFloat64OrNull(events__pdi__person.properties___tickets)) FROM events INNER JOIN "
            "(SELECT argMax(person_distinct_id2.person_id, person_distinct_id2.version) AS person_id, person_distinct_id2.distinct_id FROM person_distinct_id2 "
            f"WHERE equals(person_distinct_id2.team_id, {self.team.pk}) GROUP BY person_distinct_id2.distinct_id HAVING equals(argMax(person_distinct_id2.is_deleted, person_distinct_id2.version), 0)) AS events__pdi "
            "ON equals(events.distinct_id, events__pdi.distinct_id) INNER JOIN (SELECT "
            "argMax(replaceRegexpAll(JSONExtractRaw(person.properties, %(hogql_val_0)s), '^\"|\"$', ''), person.version) AS properties___tickets, "
            f"person.id FROM person WHERE equals(person.team_id, {self.team.pk}) GROUP BY person.id HAVING equals(argMax(person.is_deleted, person.version), 0)) AS events__pdi__person "
            f"ON equals(events__pdi.person_id, events__pdi__person.id) WHERE equals(events.team_id, {self.team.pk}) LIMIT 65535"
        )
        self.assertEqual(printed, expected)

    def test_resolve_property_types_data_beach(self):
        data_beach_table = DataBeachTable.objects.create(
            team=self.team, name="new_table", engine=DataBeachTableEngine.APPENDABLE
        )
        DataBeachField.objects.create(
            team=self.team, table=data_beach_table, name="screen_width", type=DataBeachFieldType.Integer
        )
        DataBeachField.objects.create(
            team=self.team, table=data_beach_table, name="screen_height", type=DataBeachFieldType.Integer
        )
        printed = self._print_select("select screen_width * screen_height from new_table")
        expected = (
            f"SELECT multiply(toInt64OrNull(new_table.data___screen_width), toInt64OrNull(new_table.data___screen_height)) "
            f"FROM (SELECT replaceRegexpAll(JSONExtractRaw(data_beach_appendable.data, %(hogql_val_0)s), '^\"|\"$', '') "
            f"AS data___screen_width, replaceRegexpAll(JSONExtractRaw(data_beach_appendable.data, %(hogql_val_1)s), '^\"|\"$', '') "
            f"AS data___screen_height FROM data_beach_appendable WHERE and(equals(data_beach_appendable.team_id, {self.team.pk}), "
            f"equals(data_beach_appendable.table_name, %(hogql_val_2)s))) AS new_table LIMIT 65535"
        )
        self.assertEqual(printed, expected)

    def _print_select(self, select: str):
        expr = parse_select(select)
        return print_ast(expr, HogQLContext(team_id=self.team.pk, enable_select_queries=True), "clickhouse")
