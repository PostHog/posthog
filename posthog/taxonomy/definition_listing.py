"""Statement bound shared by the event and property definition list endpoints.

Both endpoints list a hand-written query over a table that every tenant shares, so one slow list
can hold a database connection for as long as the caller waits. Bounding the statement sheds that
load at a point we choose and returns a 503 the caller can retry.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, OperationalError, connections, router, transaction
from django.db.models import Model

from prometheus_client import Counter
from rest_framework import status
from rest_framework.exceptions import APIException

# The app database sets no statement_timeout, so without this a slow list keeps consuming database
# CPU until the gateway gives up at 120s, long after the client stopped waiting for it.
DEFINITION_LIST_STATEMENT_TIMEOUT_MS = 25_000

# Postgres reports a statement cancelled by statement_timeout as SQLSTATE 57014. psycopg2 exposes
# it as `pgcode` and psycopg3 as `sqlstate`, and Django re-raises either as its own
# OperationalError, so both attribute names have to be checked on the error and on its cause.
QUERY_CANCELED_SQLSTATE = "57014"


def definition_read_db_alias(model: type[Model]) -> str:
    # The page fetch is an ORM RawQuerySet, so it follows the read router (see ReplicaRouter's
    # opt-in list). The count query and the statement timeout have to land on that same connection
    # or they describe a different session than the one doing the work. ReplicaRouter matches on
    # the model's class name, so pass the model the page query itself runs through — the
    # enterprise child, wherever EE is available — not its parent.
    return router.db_for_read(model) or DEFAULT_DB_ALIAS


def is_query_canceled(error: BaseException) -> bool:
    for exc in (error, error.__cause__):
        if exc is None:
            continue
        if (getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)) == QUERY_CANCELED_SQLSTATE:
            return True
    return False


class DefinitionListTimedOut(APIException):
    # The taxonomic filter renders a failed list the same way as an empty one, so a generic 5xx
    # here reads to the user as an empty project. A stable code lets the client tell a timed-out
    # list apart from any other server error and offer a retry instead. Each endpoint subclasses
    # this to name its own code and message.
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE


@contextmanager
def bounded_definition_list(
    alias: str,
    timed_out: type[DefinitionListTimedOut],
    timed_out_counter: Counter,
) -> Iterator[None]:
    """Bound one list request, and turn a cancelled statement into a retryable 503.

    Both the raw queries and the serialization that reads their rows have to sit inside this
    transaction, because SET LOCAL only lasts until it commits and the page fetch is a lazy
    RawQuerySet that the paginator does not evaluate until the objects are serialized.
    """
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [DEFINITION_LIST_STATEMENT_TIMEOUT_MS])
            yield
    except OperationalError as error:
        if not is_query_canceled(error):
            raise
        timed_out_counter.inc()
        raise timed_out from error
