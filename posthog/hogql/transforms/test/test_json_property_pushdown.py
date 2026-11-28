from typing import Any

from posthog.test.base import APIBaseTest, BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, InCohortVia, InlineCohortCalculation, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.group.util import create_group
from posthog.test.persons import create_person
from posthog.uuidt import UUIDT

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import recalculate_cohortpeople


class TestJSONPropertyPushdown(BaseTest):
    def _print(self, query: str, **context_options) -> str:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True, **context_options)
        printed, _ = prepare_and_print_ast(parse_select(query), context, dialect="clickhouse")
        return printed

    @parameterized.expand(["groups", "persons"])
    def test_json_extract_string_projects_single_field(self, table: str):
        printed = self._print(f"SELECT JSONExtractString(properties, 'name') AS name FROM {table}")
        self.assertIn("properties___name", printed)

    @parameterized.expand(["groups", "persons"])
    def test_json_extract_string_matches_ifnull_property_access(self, table: str):
        extract = self._print(f"SELECT JSONExtractString(properties, 'name') AS name FROM {table}")
        wrapped = self._print(f"SELECT ifNull(properties.name, '') AS name FROM {table}")
        self.assertEqual(extract, wrapped)

    def test_json_extract_string_on_a_join_to_groups_is_rewritten(self):
        printed = self._print("SELECT JSONExtractString(group_0.properties, 'probe') FROM events")
        self.assertIn("properties___probe", printed)

    def test_event_and_person_reads_through_a_join_to_events_read_their_own_columns(self):
        printed = self._print(
            "SELECT JSONExtractString(events.properties, 'label'), "
            "JSONExtractString(events.person.properties, 'label') FROM raw_session_replay_events",
            modifiers=HogQLQueryModifiers(
                personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            ),
        )
        self.assertIn(" AS properties___label,", printed)
        self.assertIn(" AS poe___properties___label,", printed)

    def test_whole_properties_access_still_aggregates_blob(self):
        printed = self._print("SELECT key, properties FROM groups")
        self.assertIn("argMax(groups.group_properties,", printed)
        self.assertNotIn("properties___name", printed)

    def test_non_constant_key_is_not_rewritten(self):
        printed = self._print("SELECT key, JSONExtractString(properties, key) AS name FROM groups")
        self.assertIn("argMax(groups.group_properties,", printed)

    def test_does_not_rewrite_on_hogql_dialect(self):
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        printed, _ = prepare_and_print_ast(
            parse_select("SELECT JSONExtractString(properties, 'name') AS name FROM groups"),
            context,
            dialect="hogql",
        )
        self.assertIn("JSONExtractString", printed)


VALUES: dict[str, Any] = {
    "plain": "plain",
    "quote": 'a"b',
    "backslash": "C:\\tmp\\new",
    "newline": "line1\nline2",
    "non_ascii": "café",
    "empty": "",
    "string_null": "null",
    "null": None,
    "number": 5,
    "boolean": True,
    "object": {"inner": 'x"y'},
    "array": ["x\\y"],
}
STRING_VALUES = {label: value for label, value in VALUES.items() if isinstance(value, str)}


class TestJSONPropertyReadValues(ClickhouseTestMixin, APIBaseTest):
    def _seed(self, table: str) -> None:
        rows = [{"label": label, "value": value} for label, value in VALUES.items()]
        for properties in [*rows, {"label": "missing"}]:
            if table == "persons":
                create_person(team=self.team, distinct_ids=[properties["label"]], properties=properties)
            else:
                create_group(
                    team_id=self.team.pk, group_type_index=0, group_key=properties["label"], properties=properties
                )

    def _read(self, table: str, expression: str) -> dict[str, str | None]:
        response = execute_hogql_query(f"SELECT properties.label, {expression} FROM {table}", team=self.team)
        return dict(response.results)

    @parameterized.expand(["persons", "groups"])
    def test_constant_key_call_matches_the_call_that_is_not_rewritten(self, table: str) -> None:
        self._seed(table)

        self.assertEqual(
            self._read(table, "JSONExtractString(properties, 'value')"),
            self._read(table, "JSONExtractString(properties, concat('val', 'ue'))"),
        )

    @parameterized.expand(["persons", "groups"])
    def test_property_access_returns_the_decoded_value(self, table: str) -> None:
        self._seed(table)

        values = self._read(table, "properties.value")

        self.assertEqual(
            {label: values[label] for label in [*STRING_VALUES, "null", "missing"]},
            {**STRING_VALUES, "null": None, "missing": None},
        )


@override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
class TestInlineCohortPersonProperty(ClickhouseTestMixin, APIBaseTest):
    """A property read inside an inlined cohort only reaches the printer as a property type, not a property access."""

    def test_inline_cohort_matches_a_person_property_with_an_escaped_quote(self):
        distinct_id = f"person-{UUIDT()}"
        create_person(team=self.team, distinct_ids=[distinct_id], properties={"name": 'a"b'}, is_identified=True)
        _create_event(distinct_id=distinct_id, event="cohort-test", team=self.team)
        flush_persons_and_events()

        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "name", "value": 'a"b', "type": "person"}]}],
        )
        recalculate_cohortpeople(cohort, pending_version=0, initiating_user_id=None)

        response = execute_hogql_query(
            f"SELECT count() FROM events WHERE person_id IN COHORT {cohort.pk}",
            self.team,
            modifiers=HogQLQueryModifiers(
                inCohortVia=InCohortVia.LEFTJOIN, inlineCohortCalculation=InlineCohortCalculation.ALWAYS
            ),
        )

        self.assertEqual(response.results, [(1,)])
