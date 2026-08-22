from parameterized import parameterized

from posthog.exception_autocapture_filter import drop_transient_connection_errors


def _exception_event(exc_type: str, value: str) -> dict:
    return {"event": "$exception", "properties": {"$exception_list": [{"type": exc_type, "value": value}]}}


class TestDropTransientConnectionErrors:
    @parameterized.expand(
        [
            ("dns_translate", "OperationalError", 'could not translate host name "db" to address'),
            ("dns_temporary_failure", "OperationalError", "Temporary failure in name resolution"),
            ("connection_refused", "OperationalError", 'connection to server at "db" failed: Connection refused'),
            ("interface_closed", "InterfaceError", "server closed the connection unexpectedly"),
            ("db_starting_up", "OperationalError", "the database system is starting up"),
        ]
    )
    def test_drops_transient_connection_events(self, _name: str, exc_type: str, value: str) -> None:
        assert drop_transient_connection_errors(_exception_event(exc_type, value)) is None

    @parameterized.expand(
        [
            # A real defect keeps reaching error tracking, even one whose message mentions a
            # connection — only connection-error types are eligible for the transient markers.
            ("value_error_mentions_refused", "ValueError", "Connection refused by the widget parser"),
            ("genuine_operational_error", "OperationalError", 'relation "posthog_team" does not exist'),
        ]
    )
    def test_keeps_real_exception_events(self, _name: str, exc_type: str, value: str) -> None:
        event = _exception_event(exc_type, value)
        assert drop_transient_connection_errors(event) is event

    @parameterized.expand(
        [
            # A genuine defect that wraps a transient DB error keeps reaching error tracking: only
            # the outermost ($exception_list[0]) exception decides the drop.
            (
                "wrapper_over_transient_cause_kept",
                [
                    {"type": "RuntimeError", "value": "Unable to ensure catalog exists"},
                    {"type": "OperationalError", "value": 'connection to server at "db" failed: Connection refused'},
                ],
                False,
            ),
            # The boot-race failure Django re-raises as OperationalError, chaining the driver error
            # as its cause, is still dropped: the outermost entry is the transient connection error.
            (
                "transient_outermost_dropped",
                [
                    {"type": "OperationalError", "value": 'connection to server at "db" failed: Connection refused'},
                    {"type": "OperationalError", "value": "connection refused"},
                ],
                True,
            ),
        ]
    )
    def test_classifies_only_outermost_exception(self, _name: str, exception_list: list[dict], dropped: bool) -> None:
        event = {"event": "$exception", "properties": {"$exception_list": exception_list}}
        result = drop_transient_connection_errors(event)
        if dropped:
            assert result is None
        else:
            assert result is event

    def test_passes_through_non_exception_events(self) -> None:
        event = {"event": "$pageview", "properties": {}}
        assert drop_transient_connection_errors(event) is event

    def test_handles_missing_exception_list(self) -> None:
        event = {"event": "$exception", "properties": {}}
        assert drop_transient_connection_errors(event) is event
