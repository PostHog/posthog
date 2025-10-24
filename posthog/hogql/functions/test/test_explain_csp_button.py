from posthog.test.base import BaseTest

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query


class TestExplainCSPReport(BaseTest):
    def test_explain_csp_report(self):
        response = execute_hogql_query(
            "select explainCSPReport({'violated_directive': 'script-src', 'original_policy': 'script-src https://example.com'})",
            self.team,
            pretty=False,
        )
        self.assertEqual(
            response.clickhouse,
            "SELECT tuple(%(hogql_val_0)s, %(hogql_val_1)s, %(hogql_val_2)s, tuple(%(hogql_val_3)s, %(hogql_val_4)s, %(hogql_val_5)s, %(hogql_val_6)s, %(hogql_val_7)s, %(hogql_val_8)s)) LIMIT 100 SETTINGS readonly=2, max_execution_time=60, allow_experimental_object_type=1, format_csv_allow_double_quotes=0, max_ast_elements=4000000, max_expanded_ast_elements=4000000, max_bytes_before_external_group_by=0, transform_null_in=1, optimize_min_equality_disjunction_chain_length=4294967295, allow_experimental_join_condition=1",
        )
        self.assertEqual(
            response.hogql,
            "SELECT tuple('__hx_tag', 'ExplainCSPReport', 'properties', tuple('__hx_tag', '__hx_obj', 'violated_directive', 'script-src', 'original_policy', 'script-src https://example.com')) LIMIT 100",
        )
        self.assertEqual(
            response.results[0][0],
            (
                "__hx_tag",
                "ExplainCSPReport",
                "properties",
                (
                    "__hx_tag",
                    "__hx_obj",
                    "violated_directive",
                    "script-src",
                    "original_policy",
                    "script-src https://example.com",
                ),
            ),
        )

    def test_explain_csp_report_no_properties_error(self):
        with self.assertRaises(QueryError) as e:
            execute_hogql_query(f"SELECT explainCSPReport()", self.team)
        self.assertEqual(str(e.exception), "Function 'explainCSPReport' expects 1 argument, found 0")
