from typing import Any

from posthog.test.base import BaseTest

from posthog.schema import AssistantHogQLQuery

from .. import TRUNCATED_MARKER, SQLResultsFormatter


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

    def test_format_truncates_large_dict(self):
        query = AssistantHogQLQuery(query="SELECT properties")
        large_dict = {"key_" + str(i): "value_" + str(i) * 50 for i in range(20)}
        results = [{"properties": large_dict}]
        columns = ["properties"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertIn(TRUNCATED_MARKER, output)
        self.assertTrue(formatter.has_truncated_values)
        # The cell content should be truncated
        cell_content = output.split("\n")[1]
        self.assertLess(len(cell_content), len(str(large_dict)))

    def test_format_truncates_large_list(self):
        query = AssistantHogQLQuery(query="SELECT items")
        large_list = ["item_" + str(i) * 50 for i in range(20)]
        results = [{"items": large_list}]
        columns = ["items"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertIn(TRUNCATED_MARKER, output)
        self.assertTrue(formatter.has_truncated_values)

    def test_format_does_not_truncate_small_dict(self):
        query = AssistantHogQLQuery(query="SELECT properties")
        small_dict = {"key": "value", "another": "data"}
        results = [{"properties": small_dict}]
        columns = ["properties"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertNotIn(TRUNCATED_MARKER, output)
        self.assertFalse(formatter.has_truncated_values)
        self.assertIn(str(small_dict), output)

    def test_format_does_not_truncate_small_list(self):
        query = AssistantHogQLQuery(query="SELECT items")
        small_list = ["a", "b", "c"]
        results = [{"items": small_list}]
        columns = ["items"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertNotIn(TRUNCATED_MARKER, output)
        self.assertFalse(formatter.has_truncated_values)
        self.assertIn(str(small_list), output)

    def test_format_truncation_at_boundary(self):
        query = AssistantHogQLQuery(query="SELECT data")
        # Create a dict that's exactly at the boundary
        boundary_dict = {"x": "y" * (SQLResultsFormatter.MAX_CELL_LENGTH - 10)}
        results = [{"data": boundary_dict}]
        columns = ["data"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        # Should be truncated since str(boundary_dict) > MAX_CELL_LENGTH
        if len(str(boundary_dict)) > SQLResultsFormatter.MAX_CELL_LENGTH:
            self.assertIn(TRUNCATED_MARKER, output)
            self.assertTrue(formatter.has_truncated_values)
        else:
            self.assertNotIn(TRUNCATED_MARKER, output)
            self.assertFalse(formatter.has_truncated_values)

    def test_format_truncates_stringified_json_dict(self):
        query = AssistantHogQLQuery(query="SELECT json_data")
        # Stringified JSON object
        large_json_str = '{"key_' + '0": "' + "x" * 600 + '"}'
        results = [{"json_data": large_json_str}]
        columns = ["json_data"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertIn(TRUNCATED_MARKER, output)
        self.assertTrue(formatter.has_truncated_values)

    def test_format_truncates_stringified_json_array(self):
        query = AssistantHogQLQuery(query="SELECT json_data")
        # Stringified JSON array
        large_json_str = '["' + "x" * 600 + '"]'
        results = [{"json_data": large_json_str}]
        columns = ["json_data"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertIn(TRUNCATED_MARKER, output)
        self.assertTrue(formatter.has_truncated_values)

    def test_format_does_not_truncate_small_stringified_json(self):
        query = AssistantHogQLQuery(query="SELECT json_data")
        small_json_str = '{"key": "value"}'
        results = [{"json_data": small_json_str}]
        columns = ["json_data"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        self.assertNotIn(TRUNCATED_MARKER, output)
        self.assertFalse(formatter.has_truncated_values)
        self.assertIn(small_json_str, output)

    def test_format_does_not_truncate_long_regular_string(self):
        query = AssistantHogQLQuery(query="SELECT description")
        # Long string that doesn't look like JSON
        long_string = "x" * 600
        results = [{"description": long_string}]
        columns = ["description"]

        formatter = SQLResultsFormatter(query, results, columns)
        output = formatter.format()

        # Regular strings should NOT be truncated
        self.assertNotIn(TRUNCATED_MARKER, output)
        self.assertFalse(formatter.has_truncated_values)
        self.assertIn(long_string, output)
