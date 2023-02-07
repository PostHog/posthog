from posthog.hogql.print_string import print_clickhouse_identifier
from posthog.test.base import BaseTest


class TestPrintString(BaseTest):
    def test_sanitize_clickhouse_identifier(self):
        self.assertEqual(print_clickhouse_identifier("a"), "a")
        self.assertEqual(print_clickhouse_identifier("a a a"), "`a a a`")
        self.assertEqual(print_clickhouse_identifier("a#$%#"), "`a#$%#`")
        self.assertEqual(print_clickhouse_identifier("a"), "a")
