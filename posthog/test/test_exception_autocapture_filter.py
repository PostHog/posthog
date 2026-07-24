from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.errors import ParsingError, QueryError, ResolutionError, SyntaxError

from posthog.exception_autocapture_filter import drop_user_query_errors


def _exception_entry(error_class: type) -> dict:
    return {"type": error_class.__name__, "module": error_class.__module__, "value": "boom"}


def _exception_event(*error_classes: type) -> dict:
    return {"event": "$exception", "properties": {"$exception_list": [_exception_entry(c) for c in error_classes]}}


class TestDropUserQueryErrors(SimpleTestCase):
    @parameterized.expand(
        [
            ("query_error", QueryError),
            ("syntax_error", SyntaxError),
            ("resolution_error", ResolutionError),
        ]
    )
    def test_drops_user_hogql_error(self, _name: str, error_class: type) -> None:
        assert drop_user_query_errors(_exception_event(error_class)) is None

    def test_drops_chain_of_only_user_errors(self) -> None:
        # QueryError raised from a ResolutionError cause: both are user errors, so drop.
        assert drop_user_query_errors(_exception_event(ResolutionError, QueryError)) is None

    def test_keeps_chain_with_a_non_user_error(self) -> None:
        # ParsingError is a genuine engine fault, not user input: keep the whole event.
        event = _exception_event(ParsingError, QueryError)
        assert drop_user_query_errors(event) is event

    @parameterized.expand(
        [
            ("parsing_error", ParsingError),
            ("value_error", ValueError),
        ]
    )
    def test_keeps_non_dropped_error(self, _name: str, error_class: type) -> None:
        event = _exception_event(error_class)
        assert drop_user_query_errors(event) is event

    def test_passes_through_non_exception_event(self) -> None:
        event = {"event": "$pageview", "properties": {"$current_url": "https://example.com"}}
        assert drop_user_query_errors(event) is event
