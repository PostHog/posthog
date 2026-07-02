"""Filter interrupt/exit signals out of exception autocapture.

`posthoganalytics.enable_exception_autocapture = True` (see `posthog/apps.py`) installs a
`sys.excepthook` that captures *any* uncaught `BaseException` as an error tracking issue —
including `KeyboardInterrupt` and `SystemExit`. Those aren't bugs: they mean the process was
Ctrl+C'd or asked to exit (e.g. a management/preflight script interrupted while Django's
`AppConfig.ready()` blocks on a Postgres connect). Each one still spawns a brand-new issue
that someone has to triage and dismiss.

Wired as the SDK's `before_send` hook, `drop_interrupt_exceptions` drops any captured
`$exception` event whose exception chain is an interrupt/exit signal, while leaving every
real exception untouched.
"""

from typing import Any

# Signal-style BaseExceptions that mean "the process was interrupted / asked to exit",
# not "a bug happened". Matched by SDK-serialized type name (`$exception_list[*].type`).
INTERRUPT_EXCEPTION_TYPES = frozenset({"KeyboardInterrupt", "SystemExit"})


def drop_interrupt_exceptions(event: Any) -> Any:
    """`before_send` hook: return `None` to drop autocaptured interrupt/exit exceptions.

    No-op for every other event. Never raises — the SDK try/excepts `before_send`, but a hook
    that threw would fall back to sending the event anyway, defeating the filter.
    """
    try:
        if not isinstance(event, dict) or event.get("event") != "$exception":
            return event
        properties = event.get("properties")
        if not isinstance(properties, dict):
            return event
        exception_list = properties.get("$exception_list")
        if not isinstance(exception_list, list):
            return event
        for exception in exception_list:
            if isinstance(exception, dict) and exception.get("type") in INTERRUPT_EXCEPTION_TYPES:
                return None
        return event
    except Exception:
        return event
