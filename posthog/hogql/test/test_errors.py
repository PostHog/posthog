from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import humanize_hogql_parse_error


class TestHumanizeHogqlParseError(SimpleTestCase):
    @parameterized.expand(
        [
            "trailing tokens after expression: 'WITH' (Keyword(With)) (reserved keyword cannot appear in this position)",
            "no viable alternative at input 'select from'",
            "unexpected token in expression: Keyword(With)",
            "mismatched input 'from' expecting {SELECT, WITH}",
        ]
    )
    def test_low_level_parser_wording_is_replaced(self, message: str) -> None:
        humanized = humanize_hogql_parse_error(message)
        self.assertEqual(
            humanized,
            "This isn't valid HogQL. Check for a typo, a missing comma or operator, "
            "or a reserved word used as a column or alias without quotes.",
        )
        # The rust backend Debug-prints internal token kinds; none may reach the user.
        self.assertNotIn("Keyword(", humanized)

    @parameterized.expand(
        [
            "mismatched input '<EOF>' expecting {SELECT, WITH}",
            "unexpected token in expression: Eof",
        ]
    )
    def test_end_of_input_gets_its_own_message(self, message: str) -> None:
        self.assertEqual(
            humanize_hogql_parse_error(message),
            "Unexpected end of query. Check for a missing table, column, bracket, or quote.",
        )

    def test_semantic_errors_pass_through_unchanged(self) -> None:
        message = "You don't have access to table `events`."
        self.assertEqual(humanize_hogql_parse_error(message), message)
