import sys
from typing import Any, Optional

from posthog.errors import is_user_facing_query_error_type


def _resolve_exception_type(module_name: Optional[str], type_name: Optional[str]) -> Optional[type[BaseException]]:
    """Resolve an already-imported exception class from its recorded module + name.

    Uses `sys.modules` only (never imports): the exception was just raised in-process, so its
    module is loaded. Anything not currently loaded returns None and is left untouched.
    """
    if not module_name or not type_name:
        return None
    module = sys.modules.get(module_name)
    if module is None:
        return None
    cls = getattr(module, type_name, None)
    if isinstance(cls, type) and issubclass(cls, BaseException):
        return cls
    return None


def drop_user_facing_query_errors(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """`before_send` hook for the global exception-autocapture client.

    User query errors (e.g. a HogQL query against a table that doesn't exist) surface to the user
    as a 4xx and are deliberately not captured by `QueryRunner.run()`. But once the same exception
    propagates past that inner context, the request-level context or global autocapture re-captures
    it, polluting error tracking. This hook drops those `$exception` events at the single point
    every captured event passes through, so the suppression can't be bypassed by an outer boundary.

    Returns the event unchanged for everything else; returning None drops it.
    """
    try:
        if event.get("event") != "$exception":
            return event

        exception_list = (event.get("properties") or {}).get("$exception_list") or []
        if not exception_list:
            return event

        # The raised (outermost) exception is last — the SDK reverses the walked cause chain — so
        # this mirrors what `classify_query_error(exc)` sees for the exception that became the 4xx.
        raised = exception_list[-1]
        exc_type = _resolve_exception_type(raised.get("module"), raised.get("type"))
        if exc_type is not None and is_user_facing_query_error_type(exc_type):
            return None
    except Exception:
        # Never let the filter break capture — fall through and keep the event.
        pass
    return event
