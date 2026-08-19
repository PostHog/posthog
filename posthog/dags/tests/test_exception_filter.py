from typing import Any, Optional

import pytest

from posthog.dags.exception_filter import drop_interrupt_exceptions


def _exception_event(*types: str) -> dict[str, Any]:
    return {
        "event": "$exception",
        "properties": {"$exception_list": [{"type": t, "value": "shutting down"} for t in types]},
    }


@pytest.mark.parametrize(
    "event,expected_dropped",
    [
        (_exception_event("DagsterExecutionInterruptedError"), True),
        (_exception_event("KeyboardInterrupt"), True),
        # A chained trace keeps the interrupt buried behind an import-time frame.
        (_exception_event("ImportError", "DagsterExecutionInterruptedError"), True),
        (_exception_event("ValueError"), False),
        (_exception_event(), False),
        ({"event": "$pageview", "properties": {}}, False),
    ],
)
def test_drop_interrupt_exceptions(event: dict[str, Any], expected_dropped: bool) -> None:
    result: Optional[dict[str, Any]] = drop_interrupt_exceptions(event)
    if expected_dropped:
        assert result is None
    else:
        assert result is event
