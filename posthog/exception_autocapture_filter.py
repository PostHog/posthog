"""Keep user-input HogQL query errors out of error tracking.

posthog-python exception autocapture (enabled globally in ``apps.py``) reports
any exception that propagates out of a ``new_context()`` scope. Several server
paths run, resolve, or print user-authored HogQL outside the query runner's
capture-suppressing context — query endpoint execution, data modeling
materialization, and data-warehouse schema building among them. When a user
writes an invalid query (unknown table, unsupported function, ambiguous field,
bad syntax) those paths raise a user-facing HogQL error that is returned to the
user as a 4xx. Those are user input mistakes, not server faults, so they must
not pollute error tracking.

Registered as posthoganalytics ``before_send``, ``drop_user_query_errors`` runs
for every captured event, so the non-exception fast path stays O(1).
"""

from typing import Any, Optional

from posthog.hogql import errors as hogql_errors
from posthog.hogql.errors import ExposedHogQLError, ResolutionError

# ExposedHogQLError (QueryError, SyntaxError) is user input by definition.
# ResolutionError is nominally an InternalHogQLError, but in practice it is
# raised for user-caused conditions — unknown/ambiguous tables and fields in a
# user's query — and is surfaced to the user, so it belongs in the same bucket.
_DROP_HOGQL_ERROR_BASES = (ExposedHogQLError, ResolutionError)


def _is_user_hogql_error(exception: dict[str, Any]) -> bool:
    if exception.get("module") != hogql_errors.__name__:
        return False
    error_class = getattr(hogql_errors, exception.get("type") or "", None)
    return isinstance(error_class, type) and issubclass(error_class, _DROP_HOGQL_ERROR_BASES)


def drop_user_query_errors(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    """posthoganalytics ``before_send`` hook: return ``None`` to drop, else the event.

    Drops an ``$exception`` event only when every exception in the captured chain
    is a user-input HogQL error, so a genuine server fault chained under (or over)
    a user error is still reported.
    """
    properties = event.get("properties") if isinstance(event, dict) else None
    if not properties:
        return event
    exception_list = properties.get("$exception_list")
    if not exception_list:
        return event
    if all(isinstance(exception, dict) and _is_user_hogql_error(exception) for exception in exception_list):
        return None
    return event
