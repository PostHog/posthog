from posthog.hogql.printer_utils import sanitize_clickhouse_identifier
from posthog.test.base import BaseTest


class TestPrinterUtils(BaseTest):
    def test_sanitize_clickhouse_identifier(self):
        self.assertEqual(sanitize_clickhouse_identifier("a"), "a")
        self.assertEqual(sanitize_clickhouse_identifier("a a a"), "`a a a`")
        self.assertEqual(sanitize_clickhouse_identifier("a#$%#"), "`a#$%#`")
        self.assertEqual(sanitize_clickhouse_identifier("a"), "a")
