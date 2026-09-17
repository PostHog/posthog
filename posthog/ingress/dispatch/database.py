"""A statement-timeout cap for consumers that read the database on the request path.

A provider gives a delivery one short window and mostly never retries it, so a slow query
can cost the whole delivery rather than just the piece of work that issued it. Bounding the
statement degrades that to a missing lookup.
"""

from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager

from django.conf import settings
from django.db import InterfaceError, OperationalError, connections, router, transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Model

import structlog

from posthog.ingress.observability.metrics import observe_bounded_read_reconnect

logger = structlog.get_logger(__name__)

# PostgreSQL raises query_canceled when statement_timeout fires. Django wraps the driver
# error in OperationalError, so the SQLSTATE lives on the cause -- psycopg3 spells it
# `sqlstate`, psycopg2 `pgcode`. The message check is the fallback for anything that loses
# the cause on the way up.
_QUERY_CANCELED_SQLSTATE = "57014"

# Substrings identifying a connection that died before it answered: the server, the pooler in
# front of it, or the client found the socket gone. The condition is over as soon as a fresh
# connection is used, so opening the alias again clears it.
#
# Narrow on purpose. This retry is immediate and runs inside the delivery's wall clock, so it
# must not repeat a saturated pool or a restarting server straight back into the same failure.
# `posthog/temporal/common/db_errors.py` holds the wider transient set, which suits a caller a
# Temporal retry policy backs off.
#
# The message is matched case-folded, so every marker here has to stay lowercase: libpq builds
# part of the text from the OS string, which arrives capitalized ("Connection reset by peer").
_DROPPED_CONNECTION_MARKERS = (
    "server closed the connection unexpectedly",
    "connection reset by peer",
    # The same two failures as libpq words them through the TLS layer, which a deployment that
    # sets `POSTHOG_POSTGRES_SSL_MODE` gets instead of the plain text above. A clean EOF reads
    # "SSL connection has been closed unexpectedly", and a socket-level drop reads "SSL SYSCALL
    # error: ...", whose tail is often "EOF detected" rather than the OS string.
    "ssl connection has been closed unexpectedly",
    "ssl syscall error",
    # pgbouncer's report that the backend connection assigned to a query died before answering,
    # and psycopg's report of the same dead socket found client-side. Both raise as
    # ProtocolViolation (SQLSTATE 08P01), too broad to whitelist by class because a genuine
    # protocol violation is a driver bug that must keep reaching error tracking.
    "server conn crashed",
    # psycopg 3 finding the socket gone while it waits on it, and the same driver refusing a
    # connection an earlier failure already closed. psycopg 2 words the second one differently,
    # and the Django backend picks whichever driver is installed.
    "the connection is lost",
    "the connection is closed",
    "connection already closed",
    # The server ending this backend on its own (SQLSTATE 57P01), which is what a client sees
    # when the pooler or an operator drops one connection rather than the whole server. It names
    # this connection only, so a fresh one is not refused the same way.
    "terminating connection due to administrator command",
)

# pgbouncer's server_login_retry cooldown quotes the backend failure it cached, so a marker above
# can match it, but only a caller that waits out the cooldown (15s by default) gets a different
# answer. An immediate retry does not, so it is not a dropped connection for this purpose.
_POOLER_LOGIN_COOLDOWN_MARKER = "server login has been failing, cached error"


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


def _is_dropped_connection(error: BaseException) -> bool:
    if not isinstance(error, OperationalError | InterfaceError):
        return False
    message = str(error).lower()
    if _POOLER_LOGIN_COOLDOWN_MARKER in message:
        return False
    return any(marker in message for marker in _DROPPED_CONNECTION_MARKERS)


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


def _open_capped_alias(alias: str, timeout_ms: int) -> ExitStack:
    """Open a transaction on one alias with the cap installed, and hand back what closes it."""
    connection = connections[alias]
    with ExitStack() as opening:
        # SET LOCAL dies with the transaction it was set in, so the cap only needs
        # restoring when we are joining a transaction somebody else owns -- a caller
        # wrapping this in its own atomic block, or ATOMIC_REQUESTS (which PostHog does
        # not enable today). Otherwise the commit below ends it for us.
        restore = connection.in_atomic_block
        opening.enter_context(transaction.atomic(using=alias))
        opening.enter_context(_statement_timeout(connection, timeout_ms, restore=restore))
        # Only reached when both succeeded, so the caller owns the unwind from here. A failure
        # above leaves the `with` to roll the half-open attempt back.
        return opening.pop_all()


def _capped_alias(alias: str, timeout_ms: int) -> ExitStack:
    """Same, but open the alias a second time when the first connection was already dead.

    `CONN_MAX_AGE` is 0, so installing the cap dials the alias, and a pooler that dropped the
    connection fails that dial. Consumers forgive the cap firing and nothing else, so the error
    ends the whole delivery -- and GitHub sends a delivery once, so what is lost is lost. One
    immediate retry on a fresh connection recovers it.
    """
    connection = connections[alias]
    dead_driver_connection = connection.connection
    try:
        return _open_capped_alias(alias, timeout_ms)
    except Exception as error:
        # A caller's own transaction went down with the connection, so every further statement in
        # it fails anyway: the recovery there belongs to whoever opened that transaction.
        if not _is_dropped_connection(error) or connection.in_atomic_block:
            raise
        # Rolling the failed block back can leave Django holding a connection it opened itself,
        # and dropping that one would cost the delivery a third dial for nothing.
        if connection.connection is dead_driver_connection:
            connection.close()
        try:
            stack = _open_capped_alias(alias, timeout_ms)
        except Exception:
            observe_bounded_read_reconnect(outcome="failed")
            raise
        observe_bounded_read_reconnect(outcome="recovered")
        logger.warning("ingress_bounded_read_reconnected", alias=alias, error=str(error))
        return stack


@contextmanager
def bounded_statement_timeout(timeout_ms: int, *, models: Sequence[type[Model]]) -> Iterator[None]:
    """Run a block under a per-statement timeout on each alias a read of `models` may use.

    A read routed to an alias joins that alias's open transaction, so `SET LOCAL
    statement_timeout` there caps the query regardless of read-replica routing.
    """
    with ExitStack() as stack:
        for alias in read_aliases(models):
            stack.enter_context(_capped_alias(alias, timeout_ms))
        yield
