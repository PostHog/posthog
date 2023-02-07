from posthog.hogql.parse_string import parse_string
from posthog.test.base import BaseTest


class TestParseString(BaseTest):
    def test_quote_types(self):
        self.assertEqual(parse_string("`asd`"), "asd")
        self.assertEqual(parse_string("'asd'"), "asd")
        self.assertEqual(parse_string('"asd"'), "asd")

    def test_escaped_quotes(self):
        self.assertEqual(parse_string("`a``sd`"), "a`sd")
        self.assertEqual(parse_string("'a''sd'"), "a'sd")
        self.assertEqual(parse_string('"a""sd"'), 'a"sd')

    def test_escaped_quotes_slash(self):
        self.assertEqual(parse_string("`a\\`sd`"), "a`sd")
        self.assertEqual(parse_string("'a\\'sd'"), "a'sd")
        self.assertEqual(parse_string('"a\\"sd"'), 'a"sd')

    def test_slash_escape(self):
        self.assertEqual(parse_string("`a\nsd`"), "a\nsd")
        self.assertEqual(parse_string("`a\\bsd`"), "a\bsd")
        self.assertEqual(parse_string("`a\\fsd`"), "a\fsd")
        self.assertEqual(parse_string("`a\\rsd`"), "a\rsd")
        self.assertEqual(parse_string("`a\\nsd`"), "a\nsd")
        self.assertEqual(parse_string("`a\\tsd`"), "a\tsd")
        self.assertEqual(parse_string("`a\\0sd`"), "a\0sd")
        self.assertEqual(parse_string("`a\\asd`"), "a\asd")
        self.assertEqual(parse_string("`a\\vsd`"), "a\vsd")
        self.assertEqual(parse_string("`a\\\\sd`"), "a\\sd")

    def test_slash_escape_not_escaped(self):
        self.assertEqual(parse_string("`a\\xsd`"), "a\\xsd")
        self.assertEqual(parse_string("`a\\ysd`"), "a\\ysd")
        self.assertEqual(parse_string("`a\\osd`"), "a\\osd")

    def test_slash_escape_slash_multiple(self):
        self.assertEqual(parse_string("`a\\\\nsd`"), "a\\\nsd")
        self.assertEqual(parse_string("`a\\\\n\\sd`"), "a\\\n\\sd")
        self.assertEqual(parse_string("`a\\\\n\\\\tsd`"), "a\\\n\\\tsd")
