from unittest import TestCase

from hogql_parser_rs import parse_string_literal_text

from posthog.hogql.errors import ParsingError

from ._test_parse_string import parse_string_test_factory


class TestParseStringRust(parse_string_test_factory("rust-json")):  # type: ignore
    pass


class TestParseStringRustEmptyInput(TestCase):
    # Empty input can't go in the shared factory: cpp's wheel aborts the process on "", while rust raises ParsingError.
    def test_empty_input_raises_parsing_error(self):
        with self.assertRaises(ParsingError):
            parse_string_literal_text("")
