"""A statement-timeout cap for consumers that read the database on the request path.

A provider gives a delivery one short window and mostly never retries it, so a slow query
can cost the whole delivery rather than just the piece of work that issued it. Bounding the
statement degrades that to a missing lookup.
"""

from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.db import OperationalError, connections, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model

# PostgreSQL raises query_canceled when statement_timeout fires. Django wraps the driver
# error in OperationalError, so the SQLSTATE lives on the cause -- psycopg3 spells it
# `sqlstate`, psycopg2 `pgcode`. The message check is the fallback for anything that loses
# the cause on the way up.
_QUERY_CANCELED_SQLSTATE = "57014"


def is_statement_timeout(error: Exception) -> bool:
    """Whether an error is the cap firing, rather than any other database failure.

    Callers use this to keep "the cap we installed fired" as a leading indicator: connection
    resets and other incidents raise the same class and would drown the signal.
    """
    if not isinstance(error, OperationalError):
        return False
    cause = error.__cause__
    if getattr(cause, "sqlstate", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    if getattr(cause, "pgcode", None) == _QUERY_CANCELED_SQLSTATE:
        return True
    return "statement timeout" in str(error).lower()


def read_aliases(models: Sequence[type[Model]]) -> list[str]:
    """The aliases a read of these models actually uses, deduped, in model order.

    Bounding an alias means opening it, and opening is itself unbounded -- `postgres_config`
    sets no `connect_timeout` on these aliases. So take the set from the router rather than
    assuming: reaching for an alias the caller never uses could stall the delivery on
    connection setup before the cap is installed, which is the failure this exists to
    prevent. That cuts both ways -- a fully replica-opted deployment must not be made to
    wait on the primary either.
    """
    aliases: list[str] = []
    for model in models:
        alias = router.db_for_read(model) or "default"
        if alias not in aliases and alias in settings.DATABASES:
            aliases.append(alias)
    return aliases


def _read_statement_timeout(connection: BaseDatabaseWrapper) -> str | None:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        row = cursor.fetchone()
    return row[0] if row else None


def _apply_statement_timeout(connection: BaseDatabaseWrapper, value: str) -> None:
    # set_config(..., is_local=True) is SET LOCAL, but takes the value as a bind parameter,
    # so a restored value ("30s", "0", ...) does not have to be quoted by hand.
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('statement_timeout', %s, true)", [value])


@contextmanager
def _statement_timeout(connection: BaseDatabaseWrapper, timeout_ms: int, *, restore: bool) -> Iterator[None]:
    """Cap statements on one connection, optionally putting the previous value back."""
    previous = _read_statement_timeout(connection) if restore else None
    _apply_statement_timeout(connection, f"{timeout_ms}ms")

    yield

    # Only reached when the block succeeded. If it raised, the enclosing atomic() rolls the
    # (sub)transaction back and PostgreSQL undoes SET LOCAL with it, so there is nothing to
    # restore -- and a statement on an aborted transaction would error anyway.
    if previous:
        _apply_statement_timeout(connection, previous)


@contextmanager
def bounded_statement_timeout(timeout_ms: int, *, models: Sequence[type[Model]]) -> Iterator[None]:
    """Run a block under a per-statement timeout on each alias a read of `models` may use.

    A read routed to an alias joins that alias's open transaction, so `SET LOCAL
    statement_timeout` there caps the query regardless of read-replica routing.
    """
    with ExitStack() as stack:
        for alias in read_aliases(models):
            connection = connections[alias]
            # SET LOCAL dies with the transaction it was set in, so the cap only needs
            # restoring when we are joining a transaction somebody else owns -- a caller
            # wrapping this in its own atomic block, or ATOMIC_REQUESTS (which PostHog does
            # not enable today). Otherwise the commit below ends it for us.
            restore = connection.in_atomic_block
            stack.enter_context(transaction.atomic(using=alias))
            stack.enter_context(_statement_timeout(connection, timeout_ms, restore=restore))
        yield
