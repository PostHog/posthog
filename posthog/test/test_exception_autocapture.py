import sys

from posthoganalytics.exception_utils import exceptions_from_error_tuple

from posthog.hogql.errors import QueryError, ResolutionError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.exception_autocapture import drop_user_facing_query_errors


def _exception_event(exc: BaseException) -> dict:
    """Build a `$exception` event the way the SDK serializes one before `before_send` runs."""
    try:
        raise exc
    except BaseException:
        exception_list = exceptions_from_error_tuple(sys.exc_info())
    return {"event": "$exception", "properties": {"$exception_list": exception_list}}


class TestDropUserFacingQueryErrors:
    def test_drops_hogql_query_error(self):
        event = _exception_event(QueryError("Unknown table `groups_types`."))
        assert drop_user_facing_query_errors(event) is None

    def test_drops_hogql_query_error_chained_from_cause(self):
        # Mirror `raise QueryError(...) from e`: the outermost exception decides the 4xx.
        try:
            try:
                raise KeyError("groups_types")
            except KeyError as e:
                raise QueryError("Unknown table `groups_types`.") from e
        except QueryError as exc:
            event = _exception_event(exc)
        assert drop_user_facing_query_errors(event) is None

    def test_drops_rate_limited_error(self):
        event = _exception_event(ConcurrencyLimitExceeded("too many"))
        assert drop_user_facing_query_errors(event) is None

    def test_keeps_generic_server_error(self):
        event = _exception_event(RuntimeError("a real server bug"))
        assert drop_user_facing_query_errors(event) == event

    def test_keeps_internal_hogql_error(self):
        # ResolutionError is InternalHogQLError, not exposed — a real engine bug worth capturing.
        event = _exception_event(ResolutionError("internal resolver failure"))
        assert drop_user_facing_query_errors(event) == event

    def test_passes_through_non_exception_events(self):
        event = {"event": "$pageview", "properties": {"foo": "bar"}}
        assert drop_user_facing_query_errors(event) == event

    def test_passes_through_exception_event_without_list(self):
        event = {"event": "$exception", "properties": {}}
        assert drop_user_facing_query_errors(event) == event
