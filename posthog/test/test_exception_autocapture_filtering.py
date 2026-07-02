from parameterized import parameterized

from posthog.exception_autocapture_filtering import drop_interrupt_exceptions


def _exception_event(*types: str) -> dict:
    return {
        "event": "$exception",
        "properties": {"$exception_list": [{"type": t} for t in types]},
    }


class TestDropInterruptExceptions:
    @parameterized.expand(
        [
            ("keyboard_interrupt", "KeyboardInterrupt"),
            ("system_exit", "SystemExit"),
        ]
    )
    def test_drops_interrupt_signal_exceptions(self, _name: str, exc_type: str) -> None:
        assert drop_interrupt_exceptions(_exception_event(exc_type)) is None

    def test_drops_when_interrupt_is_anywhere_in_the_chain(self) -> None:
        # $exception_list is the walked chain (root cause first); drop if any link is a signal.
        assert drop_interrupt_exceptions(_exception_event("ValueError", "KeyboardInterrupt")) is None

    @parameterized.expand(
        [
            ("real_exception", _exception_event("ValueError")),
            ("chained_real_exceptions", _exception_event("OperationalError", "RuntimeError")),
            ("non_exception_event", {"event": "$pageview", "properties": {}}),
            ("exception_without_list", {"event": "$exception", "properties": {}}),
            ("malformed_properties", {"event": "$exception", "properties": None}),
            ("malformed_event", "not-a-dict"),
        ]
    )
    def test_passes_through_untouched(self, _name: str, event: object) -> None:
        assert drop_interrupt_exceptions(event) is event
