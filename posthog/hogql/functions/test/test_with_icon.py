from posthog.test.base import BaseTest

from posthog.hogql.query import execute_hogql_query


class TestWithIcon(BaseTest):
    def test_explicit_icon_in_query_result(self):
        response = execute_hogql_query("SELECT withIcon('Claude Code', 'Claude')", self.team)

        self.assertEqual(
            response.results[0][0],
            ("__hx_tag", "BrandMarkLabel", "label", "Claude Code", "mark", "Claude"),
        )
