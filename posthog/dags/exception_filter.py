from typing import Any, Optional

# Interrupt-class exceptions raised during an expected code-server shutdown.
# Dagster's signal handler turns a SIGINT/SIGTERM into DagsterExecutionInterruptedError,
# and a raw interrupt surfaces as KeyboardInterrupt. Both land on whatever import
# frame is running at the time, so each shutdown mints a fresh error tracking issue.
# Matched by type name because before_send sees the serialized event, not the live
# exception.
INTERRUPT_EXCEPTION_TYPES = frozenset(
    {
        "DagsterExecutionInterruptedError",
        "KeyboardInterrupt",
    }
)


def drop_interrupt_exceptions(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Drop autocaptured interrupt exceptions so expected shutdowns stay silent."""
    if event.get("event") != "$exception":
        return event

    exception_list = event.get("properties", {}).get("$exception_list") or []
    if any(exception.get("type") in INTERRUPT_EXCEPTION_TYPES for exception in exception_list):
        return None

    return event


def install() -> None:
    """Route the dags process autocapture through drop_interrupt_exceptions."""
    import posthoganalytics  # noqa: PLC0415 — lets tests import the pure filter without the SDK

    posthoganalytics.before_send = drop_interrupt_exceptions  # ty: ignore[invalid-assignment]
    # Push before_send onto the client the excepthook already holds; without this
    # the filter would only apply after the next module-level capture forces setup().
    posthoganalytics.setup()
