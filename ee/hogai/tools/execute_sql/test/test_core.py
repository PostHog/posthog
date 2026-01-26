import pytest
from posthog.test.base import ClickhouseTestMixin, NonAtomicBaseTest

from parameterized import parameterized

from ee.hogai.tools.execute_sql.core import HogQLValidationError, validate_hogql_sync


class TestHogQLValidation(ClickhouseTestMixin, NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @parameterized.expand(
        [
            ("SELECT 1", "simple constant query"),
            ("SELECT event FROM events", "simple select from events"),
            ("SELECT event, count() as cnt FROM events GROUP BY event", "aggregation query"),
            ("SELECT event FROM events WHERE timestamp > now() - INTERVAL 1 DAY", "query with time filter"),
        ]
    )
    def test_valid_hogql_queries(self, query: str, description: str):
        result = validate_hogql_sync(query, self.team)
        self.assertEqual(result.query, query.rstrip(";").strip())

    @parameterized.expand(
        [
            ("", "empty query"),
            ("   ", "whitespace only"),
        ]
    )
    def test_empty_queries_raise_error(self, query: str, description: str):
        with pytest.raises(HogQLValidationError, match="Query is empty"):
            validate_hogql_sync(query, self.team)

    @parameterized.expand(
        [
            ("INVALID SQL SYNTAX", "invalid sql syntax"),
            ("SELECT * FORM events", "typo in FROM"),
            ("SELECT nonexistent_column FROM events", "nonexistent column"),
        ]
    )
    def test_invalid_hogql_queries_raise_error(self, query: str, description: str):
        with pytest.raises(HogQLValidationError):
            validate_hogql_sync(query, self.team)

    def test_query_with_trailing_semicolon_is_cleaned(self):
        result = validate_hogql_sync("SELECT 1;", self.team)
        self.assertEqual(result.query, "SELECT 1")

    def test_query_with_leading_trailing_whitespace_is_cleaned(self):
        result = validate_hogql_sync("  SELECT 1  ", self.team)
        self.assertEqual(result.query, "SELECT 1")
