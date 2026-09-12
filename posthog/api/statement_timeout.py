from collections.abc import Iterator
from contextlib import contextmanager

from django.db import OperationalError, connections, transaction
from django.db.backends.base.base import BaseDatabaseWrapper

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


def _current_statement_timeout(db: BaseDatabaseWrapper) -> str:
    with db.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


def _set_local_statement_timeout(db: BaseDatabaseWrapper, value: str) -> None:
    with db.cursor() as cursor:
        cursor.execute("SET LOCAL statement_timeout = %s", [value])


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
    db = connections[alias]
    # Inside an outer transaction this block is only a savepoint, and Postgres keeps a SET LOCAL
    # when a savepoint is released. Putting the outer value back stops the cap leaking past the
    # block. A failed block needs no restore: the rollback undoes the SET LOCAL.
    outer_value = _current_statement_timeout(db) if db.in_atomic_block else None
    try:
        with transaction.atomic(using=alias):
            _set_local_statement_timeout(db, f"{timeout_ms}ms")
            yield
            if outer_value is not None:
                _set_local_statement_timeout(db, outer_value)
    except OperationalError as error:
        if not is_query_canceled(error):
            raise
        timed_out_counter.inc()
        raise timed_out from error
