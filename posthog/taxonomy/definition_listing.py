"""Shared plumbing for the event and property definition list endpoints.

Both endpoints list a hand-written query over `posthog_eventdefinition` /
`posthog_propertydefinition`, which are shared by every tenant and are among the largest tables
in the app database. Both therefore need the same two things: the page and the count pushed into
SQL instead of being taken in Python over a fully materialized `RawQuerySet`, and a bound on how
long one list request can hold a database connection.
"""

from typing import Any, Optional

from django.db import DEFAULT_DB_ALIAS, router

from rest_framework.pagination import LimitOffsetPagination

# Listing runs two raw queries (a count, then a page fetch) that take tens of seconds on projects
# with very many definitions. The app database sets no statement_timeout, so a slow one keeps
# consuming database CPU for the whole request, long after the client stopped waiting for it.
# Bounding each statement sheds that load instead of queueing it, and returns a 503 the caller can
# retry or report. The bound is deliberately shorter than any request ceiling above it, so the
# database stops working at a point we choose rather than whenever the caller happens to hang up.
DEFINITION_LIST_STATEMENT_TIMEOUT_MS = 25_000

# Postgres reports a statement cancelled by statement_timeout as SQLSTATE 57014. psycopg2 exposes
# it as `pgcode` and psycopg3 as `sqlstate`, and Django re-raises either as its own
# OperationalError, so both attribute names have to be checked on the error and on its cause.
QUERY_CANCELED_SQLSTATE = "57014"


def definition_read_db_alias(model: type) -> str:
    # The page fetch is an ORM RawQuerySet, so it follows the read router (see ReplicaRouter's
    # opt-in list). The count query and the statement timeout have to land on that same connection
    # or they describe a different session than the one doing the work.
    return router.db_for_read(model) or DEFAULT_DB_ALIAS


def is_query_canceled(error: BaseException) -> bool:
    for exc in (error, error.__cause__):
        if exc is None:
            continue
        if (getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)) == QUERY_CANCELED_SQLSTATE:
            return True
    return False


class NotCountingLimitOffsetPaginator(LimitOffsetPagination):
    """
    The standard LimitOffsetPagination was expensive because there are very many definition models
    And we query them using a RawQuerySet that meant for each page of results we loaded all models twice
    Once to count them and a second time because we would slice them in memory

    This paginator expects the caller to have counted and paged the queryset
    """

    def set_count(self, count: int) -> None:
        self.count = count

    def get_count(self, queryset) -> int:
        """
        Determine an object count, supporting either querysets or regular lists.
        """
        if self.count is None:
            raise Exception("count must be manually set before paginating")

        return self.count

    def paginate_queryset(self, queryset, request, view=None) -> Optional[list[Any]]:
        """
        Assumes the queryset has already had pagination applied
        """
        self.count = self.get_count(queryset)
        self.limit = self.get_limit(request)
        if self.limit is None:
            return None

        self.offset = self.get_offset(request)
        self.request = request

        if self.count == 0 or self.offset > self.count:
            return []

        return list(queryset)
