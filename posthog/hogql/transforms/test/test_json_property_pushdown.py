import json

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.schema import HogQLQueryModifiers, PersonsOnEventsMode

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.clickhouse.client import sync_execute


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

    @parameterized.expand(["groups", "persons"])
    def test_json_extract_string_decodes_escapes(self, table: str):
        # A rewritten read has to decode JSON escapes, otherwise a value like `a"b` comes back as `a\"b`
        # and `= 'a"b'` matches nothing while the unrewritten `JSONExtractString` path matches.
        extract = self._print(f"SELECT JSONExtractString(properties, 'name') AS name FROM {table}")
        self.assertIn("JSONExtractString(nullIf(nullIf(JSONExtractRaw(", extract)
        self.assertIn(", ''), 'null'))", extract)

    @parameterized.expand(["groups", "persons"])
    def test_property_access_decodes_escapes(self, table: str):
        printed = self._print(f"SELECT properties.name AS name FROM {table}")
        self.assertIn("JSONExtractString(nullIf(nullIf(JSONExtractRaw(", printed)
        self.assertIn(", ''), 'null'))", printed)

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


@patch("posthoganalytics.feature_enabled", new=Mock(return_value=True))
class TestJSONPropertyPushdownValues(ClickhouseTestMixin, BaseTest):
    """The rewritten read has to return the unescaped value for every JSON escape that can appear in a property."""

    VALUES = ['a"b', "back\\slash", "line1\nline2", "café"]

    # The exact expression the ClickHouse printer emits for a `persons` / `groups` property read.
    EXPRESSION = "JSONExtractString(nullIf(nullIf(JSONExtractRaw(%(doc)s, 'name'), ''), 'null'))"

    def test_rewritten_read_decodes_json_escapes(self):
        for value in self.VALUES:
            result = sync_execute(f"SELECT {self.EXPRESSION} AS value", {"doc": json.dumps({"name": value})})
            self.assertEqual(result[0][0], value, value)

    @parameterized.expand(
        [
            ("empty_string_stays_empty", '{"name": ""}', ""),
            ("json_null_reads_as_null", '{"name": null}', None),
            ("missing_key_reads_as_null", '{"other": 1}', None),
            ("nullable_string_is_not_null", '{"name": "null"}', "null"),
        ]
    )
    def test_rewritten_read_keeps_the_null_contract(self, _name: str, document: str, expected: str | None):
        result = sync_execute(f"SELECT {self.EXPRESSION} AS value", {"doc": document})
        self.assertEqual(result[0][0], expected, _name)
