from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.apps import _drop_control_flow_exceptions


class TestDropControlFlowExceptions(SimpleTestCase):
    @parameterized.expand(["KeyboardInterrupt", "SystemExit"])
    def test_drops_control_flow_exception_events(self, exception_type: str) -> None:
        event = {"event": "$exception", "properties": {"$exception_list": [{"type": exception_type}]}}

        assert _drop_control_flow_exceptions(event) is None

    def test_passes_through_real_exception_events(self) -> None:
        event = {"event": "$exception", "properties": {"$exception_list": [{"type": "ValueError"}]}}

        assert _drop_control_flow_exceptions(event) is event

    def test_ignores_non_exception_events(self) -> None:
        event = {"event": "$pageview", "properties": {}}

        assert _drop_control_flow_exceptions(event) is event
