from posthog.hogql.print_string import print_hogql_identifier
from posthog.test.base import BaseTest


class TestPrintString(BaseTest):
    def test_sanitize_clickhouse_identifier(self):
        self.assertEqual(print_hogql_identifier("a"), "a")
        self.assertEqual(print_hogql_identifier("$browser"), "$browser")
        self.assertEqual(print_hogql_identifier("event"), "event")
        self.assertEqual(print_hogql_identifier("a b c"), "`a b c`")
        self.assertEqual(print_hogql_identifier("a.b.c"), "`a.b.c`")
        self.assertEqual(print_hogql_identifier("a-b-c"), "`a-b-c`")
        self.assertEqual(print_hogql_identifier("a#$%#"), "`a#$%#`")
