from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast


class TestJSONPropertyPushdown(BaseTest):
    def _print(self, query: str) -> str:
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
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
