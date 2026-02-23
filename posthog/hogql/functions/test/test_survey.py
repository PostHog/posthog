from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.errors import QueryError
from posthog.hogql.query import execute_hogql_query


class TestGetSurveyResponse(BaseTest):
    def test_single_choice_includes_numeric_fallback(self):
        result = execute_hogql_query(
            "SELECT getSurveyResponse(0, 'q1') FROM events",
            team=self.team,
        )
        assert result.clickhouse is not None
        self.assertIn("JSONExtractString", result.clickhouse)
        self.assertIn("JSONExtractInt", result.clickhouse)
        self.assertIn("JSONType", result.clickhouse)
        self.assertIn("toString", result.clickhouse)

    def test_dynamic_key_includes_numeric_fallback(self):
        result = execute_hogql_query(
            "SELECT getSurveyResponse(0) FROM events",
            team=self.team,
        )
        assert result.clickhouse is not None
        self.assertIn("JSONExtractInt", result.clickhouse)
        self.assertIn("JSONType", result.clickhouse)

    def test_multiple_choice_does_not_include_numeric_fallback(self):
        result = execute_hogql_query(
            "SELECT getSurveyResponse(0, 'q1', true) FROM events",
            team=self.team,
        )
        assert result.clickhouse is not None
        self.assertIn("JSONExtractArrayRaw", result.clickhouse)
        self.assertNotIn("JSONExtractInt", result.clickhouse)

    @parameterized.expand(
        [
            ("index_0", 0, "$survey_response"),
            ("index_1", 1, "$survey_response_1"),
            ("index_2", 2, "$survey_response_2"),
        ]
    )
    def test_index_based_key(self, _name, question_index, expected_key):
        result = execute_hogql_query(
            f"SELECT getSurveyResponse({question_index}, 'q1') FROM events",
            team=self.team,
        )
        assert result.clickhouse is not None
        self.assertIn(expected_key, result.clickhouse)

    def test_all_coalesce_branches_return_string_type(self):
        result = execute_hogql_query(
            "SELECT getSurveyResponse(0, 'q1') FROM events",
            team=self.team,
        )
        assert result.clickhouse is not None
        # toString wraps JSONExtractInt so all branches return String
        self.assertNotIn("Float64", result.clickhouse)
        self.assertNotIn("accurateCastOrNull", result.clickhouse)

    def test_rejects_non_constant_index(self):
        with self.assertRaises(QueryError):
            execute_hogql_query(
                "SELECT getSurveyResponse(uuid) FROM events",
                team=self.team,
            )

    def test_rejects_non_integer_index(self):
        with self.assertRaises(QueryError):
            execute_hogql_query(
                "SELECT getSurveyResponse('abc') FROM events",
                team=self.team,
            )
