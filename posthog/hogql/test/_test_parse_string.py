from typing import Literal

from posthog.test.base import BaseTest

from hogql_parser import parse_string_literal_text as parse_string_cpp

from posthog.hogql.errors import SyntaxError
from posthog.hogql.parse_string import parse_string_literal_text as parse_string_py


def parse_string_test_factory(backend: Literal["python", "cpp"]):
    parse_string = parse_string_py if backend == "python" else parse_string_cpp

    class TestParseString(BaseTest):
        def test_quote_types(self):
            self.assertEqual(parse_string("`asd`"), "asd")
            self.assertEqual(parse_string("'asd'"), "asd")
            self.assertEqual(parse_string('"asd"'), "asd")
            self.assertEqual(parse_string("{asd}"), "asd")

        def test_escaped_quotes(self):
            self.assertEqual(parse_string("`a``sd`"), "a`sd")
            self.assertEqual(parse_string("'a''sd'"), "a'sd")
            self.assertEqual(parse_string('"a""sd"'), 'a"sd')
            self.assertEqual(parse_string("{a{{sd}"), "a{sd")
            self.assertEqual(parse_string("{a}sd}"), "a}sd")

        def test_escaped_quotes_slash(self):
            self.assertEqual(parse_string("`a\\`sd`"), "a`sd")
            self.assertEqual(parse_string("'a\\'sd'"), "a'sd")
            self.assertEqual(parse_string('"a\\"sd"'), 'a"sd')
            self.assertEqual(parse_string("{a\\{sd}"), "a{sd")

        def test_slash_escape(self):
            self.assertEqual(parse_string("`a\nsd`"), "a\nsd")
            self.assertEqual(parse_string("`a\\bsd`"), "a\bsd")
            self.assertEqual(parse_string("`a\\fsd`"), "a\fsd")
            self.assertEqual(parse_string("`a\\rsd`"), "a\rsd")
            self.assertEqual(parse_string("`a\\nsd`"), "a\nsd")
            self.assertEqual(parse_string("`a\\tsd`"), "a\tsd")
            self.assertEqual(parse_string("`a\\asd`"), "a\asd")
            self.assertEqual(parse_string("`a\\vsd`"), "a\vsd")
            self.assertEqual(parse_string("`a\\\\sd`"), "a\\sd")
            self.assertEqual(parse_string("`a\\0sd`"), "asd")

        def test_slash_escape_not_escaped(self):
            self.assertEqual(parse_string("`a\\xsd`"), "a\\xsd")
            self.assertEqual(parse_string("`a\\ysd`"), "a\\ysd")
            self.assertEqual(parse_string("`a\\osd`"), "a\\osd")

        def test_slash_escape_slash_multiple(self):
            self.assertEqual(parse_string("`a\\\\nsd`"), "a\\\nsd")
            self.assertEqual(parse_string("`a\\\\n\\sd`"), "a\\\n\\sd")
            self.assertEqual(parse_string("`a\\\\n\\\\tsd`"), "a\\\n\\\tsd")

        def test_raises_on_mismatched_quotes(self):
            self.assertRaisesMessage(
                SyntaxError,
                "Invalid string literal, must start and end with the same quote type: `asd'",
                parse_string,
                "`asd'",
            )

    return TestParseString
