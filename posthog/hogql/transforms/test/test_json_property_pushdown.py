from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


class TestJSONPropertyPushdown(BaseTest):
    def _print(self, query: str) -> str:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        printed, _ = prepare_and_print_ast(parse_select(query), context, dialect="clickhouse")
        return printed

    def test_json_extract_string_on_groups_projects_into_argmax(self):
        printed = self._print("SELECT key, JSONExtractString(properties, 'name') AS name FROM groups")
        self.assertIn("properties___name", printed)
        self.assertNotIn("argMax(tuple(groups.group_properties)", printed)

    def test_json_extract_string_matches_property_access(self):
        extract = self._print("SELECT key, JSONExtractString(properties, 'name') AS name FROM groups")
        property_access = self._print("SELECT key, properties.name AS name FROM groups")
        self.assertEqual(extract, property_access)

    def test_whole_properties_access_still_aggregates_blob(self):
        printed = self._print("SELECT key, properties FROM groups")
        self.assertIn("argMax(tuple(groups.group_properties)", printed)
        self.assertNotIn("properties___name", printed)

    def test_non_constant_key_is_not_rewritten(self):
        printed = self._print("SELECT key, JSONExtractString(properties, key) AS name FROM groups")
        self.assertIn("argMax(tuple(groups.group_properties)", printed)
