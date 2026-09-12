from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connections, transaction

from rest_framework import status
from rest_framework.exceptions import APIException

# Listing definitions runs a count and a page fetch that take seconds on projects with very many
# rows. The app database sets no statement_timeout, so a slow one keeps consuming database CPU for
# the full request until the gateway gives up at 120s, long after the client stopped waiting for it.
# Bounding each statement well below that ceiling sheds the load instead of queueing it, and
# returns a 503 the caller can retry or report.
DEFINITION_LIST_STATEMENT_TIMEOUT_MS = 25_000

# Postgres reports a statement cancelled by statement_timeout as SQLSTATE 57014. psycopg2 exposes
# it as `pgcode` and psycopg3 as `sqlstate`, and Django re-raises either as its own
# OperationalError, so both attribute names have to be checked on the error and on its cause.
QUERY_CANCELED_SQLSTATE = "57014"


def is_query_canceled(error: BaseException) -> bool:
    for exc in (error, error.__cause__):
        if exc is None:
            continue
        if (getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)) == QUERY_CANCELED_SQLSTATE:
            return True
    return False


class DefinitionListTimedOut(APIException):
    # The taxonomic filter renders a failed list the same way as an empty one, so a generic 5xx here
    # reads to the user as "this project has nothing". A stable code per endpoint lets the client tell
    # a timed-out list apart from any other server error and offer a retry instead.
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


@contextmanager
def bounded_statement_timeout(db_alias: str, timeout_ms: int) -> Iterator[None]:
    """Run the block in one transaction on `db_alias` with `timeout_ms` as the statement timeout.

    SET LOCAL lasts until the transaction ends, so every statement the block runs has to sit inside
    it, including a lazy RawQuerySet that a paginator only evaluates while serializing.
    """
    with transaction.atomic(using=db_alias):
        with connections[db_alias].cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
        yield
