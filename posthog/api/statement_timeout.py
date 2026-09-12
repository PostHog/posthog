from collections.abc import Iterator
from contextlib import contextmanager

from django.db import OperationalError, connections, transaction

from prometheus_client import Counter
from rest_framework.exceptions import APIException

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


@contextmanager
def statement_timeout(
    alias: str,
    timeout_ms: int,
    timed_out: type[APIException],
    timed_out_counter: Counter,
) -> Iterator[None]:
    """Cap every statement on `alias` inside the block, and raise `timed_out` when one is cancelled.

    Everything that runs a query has to sit inside this block, including code that evaluates a
    lazy queryset, because SET LOCAL only lasts until the transaction commits.
    """
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = %s", [timeout_ms])
            yield
    except OperationalError as error:
        if not is_query_canceled(error):
            raise
        timed_out_counter.inc()
        raise timed_out from error
