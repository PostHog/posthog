from unittest import TestCase

from posthog.hogql.errors import SyntaxError


class TestSyntaxErrorHumanizesParserMessages(TestCase):
    """The cpp (ANTLR) and rust parsers report running off the end of a query with different raw
    text (`mismatched input '<EOF>' expecting ...` vs `unexpected token in expression: Eof`).
    Both used to reach the user verbatim; they must collapse into one human-readable message."""

    def test_antlr_eof_message_is_humanized(self) -> None:
        err = SyntaxError("mismatched input '<EOF>' expecting {SELECT, WITH, '{', '(', '<'}")
        assert str(err) == "Unexpected end of query. Check for a missing closing bracket, quote, or clause."

    def test_rust_eof_message_is_humanized(self) -> None:
        err = SyntaxError("unexpected token in expression: Eof")
        assert str(err) == "Unexpected end of query. Check for a missing closing bracket, quote, or clause."

    def test_unrelated_mismatched_input_message_is_untouched(self) -> None:
        # Only the case where EOF is the *actual* input should be humanized - a message where
        # EOF is merely one of the *expected* tokens (e.g. "mismatched input 'query' expecting
        # <EOF>") is a different, still-useful diagnostic and must pass through unchanged.
        message = "mismatched input 'query' expecting <EOF>"
        err = SyntaxError(message)
        assert str(err) == message
