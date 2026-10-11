from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from common.hogvm.python.objects import new_hog_error
from common.hogvm.python.stl.print import escape_identifier, print_hog_value


class TestEscapeIdentifier:
    def test_doubles_embedded_backtick(self):
        # The HogQL/Hog parsers only accept a doubled backtick inside a quoted identifier, not a backslash-escaped one.
        assert escape_identifier("a`b") == "`a``b`"

    @parameterized.expand(
        [
            ("plain", "normal_id"),
            ("space", "a b"),
            ("single_backtick", "`"),
            ("embedded_backtick", "a`b"),
            ("backslash", "a\\b"),
            ("tab", "a\tb"),
            ("backtick_and_backslash", "a`\\b"),
        ]
    )
    def test_round_trips_through_parser(self, _name: str, identifier: str) -> None:
        node = parse_expr(escape_identifier(identifier))
        assert isinstance(node, ast.Field)
        assert node.chain == [identifier]


class TestPrintHogValue:
    def test_error_with_itself_as_payload(self):
        error = new_hog_error("Error", "x")
        error["payload"] = error
        assert print_hog_value(error) == "Error('x', null)"
