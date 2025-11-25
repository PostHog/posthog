from typing import Any

from posthog.test.base import BaseTest

from posthog.schema import AssistantHogQLQuery

from .. import SQLResultsFormatter


class TestSQLResultsFormatter(BaseTest):
    def test_format_basic(self):
        query = AssistantHogQLQuery(query="SELECT 1")
        results = [
            {"column1": "value1", "column2": "value2"},
            {"column1": "value3", "column2": "value4"},
        ]
        columns = ["column1", "column2"]

        formatter = SQLResultsFormatter(query, results, columns)
        expected = "column1|column2\nvalue1|value2\nvalue3|value4"
        self.assertEqual(formatter.format(), expected)

    def test_format_empty_results(self):
        query = AssistantHogQLQuery(query="SELECT 1")
        results: list[Any] = []
        columns = ["column1", "column2"]

        formatter = SQLResultsFormatter(query, results, columns)
        expected = "column1|column2"
        self.assertEqual(formatter.format(), expected)

    def test_format_single_column(self):
        query = AssistantHogQLQuery(query="SELECT count()")
        results = [{"count": 42}, {"count": 100}]
        columns = ["count"]

        formatter = SQLResultsFormatter(query, results, columns)
        expected = "count\n42\n100"
        self.assertEqual(formatter.format(), expected)

    def test_format_with_none_values(self):
        query = AssistantHogQLQuery(query="SELECT id, name")
        results: list[Any] = [
            {"id": 1, "name": "test"},
            {"id": 2, "name": None},
        ]
        columns = ["id", "name"]

        formatter = SQLResultsFormatter(query, results, columns)
        expected = "id|name\n1|test\n2|None"
        self.assertEqual(formatter.format(), expected)

    def test_format_with_numeric_values(self):
        query = AssistantHogQLQuery(query="SELECT count, avg")
        results = [
            {"count": 100, "avg": 15.5},
            {"count": 200, "avg": 25.75},
        ]
        columns = ["count", "avg"]

        formatter = SQLResultsFormatter(query, results, columns)
        expected = "count|avg\n100|15.5\n200|25.75"
        self.assertEqual(formatter.format(), expected)
