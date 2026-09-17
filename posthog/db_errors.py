from django.db import InterfaceError, InternalError, OperationalError

# Substrings identifying a backend connection that died mid-query: the server, the pooler, or the
# client found the socket gone. The condition is over as soon as a fresh connection is used, so
# the recovery is to drop the dead connection and run the query again.
_DROPPED_CONNECTION_MARKERS = (
    "server closed the connection unexpectedly",
    "connection reset by peer",
    # pgbouncer's report that the backend connection assigned to an in-flight query died before
    # answering, and psycopg's report of the same dead socket found client-side. psycopg raises
    # both as ProtocolViolation (SQLSTATE 08P01), which is too broad to whitelist by class because
    # a genuine protocol violation is a driver bug that must keep reaching error tracking, so
    # match the message. Also reaches us wrapped in pgbouncer's cached-login message below.
    "server conn crashed",
    # Reuse of a connection a previous failure already closed. psycopg 3 and psycopg 2 word this
    # differently, and the Django postgresql backend picks whichever driver is installed.
    "the connection is closed",
    "connection already closed",
)

# Substrings identifying transient Postgres failures. pgbouncer kills queries that wait too long
# for a backend connection with `query_wait_timeout`, and surfaces dropped/reset backend
# connections as closed or reset connections. Both clear on their own, so a Temporal retry
# resolves them. Deliberately excludes psycopg's generic "connection failed:" prefix, which
# covers every failed connect including persistent misconfiguration (bad credentials,
# nonexistent database, unresolvable host) that must keep reaching error tracking.
_TRANSIENT_DB_ERROR_MARKERS = (
    *_DROPPED_CONNECTION_MARKERS,
    "query_wait_timeout",
    "the database system is starting up",
    "the database system is shutting down",
    # pgbouncer's server_login_retry cooldown: a backend connect attempt failed, so pgbouncer
    # caches the failure and hands it to every client asking for a connection until the cooldown
    # (default 15s) elapses and it retries the backend itself. Self-heals without our retry doing
    # anything special, so it's transient by construction, not a symptom of the underlying cause.
    "server login has been failing, cached error",
    # The pooler (pgbouncer/pgcat) itself draining for a restart or deploy, refusing new
    # connections while it does. Same self-healing shape as "the database system is shutting
    # down" above, just raised by the pooler in front of Postgres rather than Postgres itself.
    # A connect failure through a pooler, so no SQLSTATE — falls through to this message match.
    "pooler is shutting down",
)

# SQLSTATE class 57P (operator intervention): the server is shutting down or restarting and
# refusing work while it does, which clears once it comes back. Available on the wrapped
# psycopg error for server-raised failures; connect failures carry no SQLSTATE and fall
# through to the message markers above.
_TRANSIENT_SQLSTATE_PREFIXES = ("57P",)

# read_only_sql_transaction: a primary/replica failover briefly leaves the connection's target
# read-only until promotion finishes or the pooler redirects to the new primary. Matched exactly
# rather than by class prefix, because SQLSTATE class 25 (invalid transaction state) also covers
# codes that are real transaction-handling bugs, not infra hiccups. psycopg raises this under
# InternalError, not OperationalError, hence the wider isinstance check below.
_TRANSIENT_SQLSTATES = ("25006",)


def is_transient_db_error(error: BaseException) -> bool:
    if not isinstance(error, OperationalError | InterfaceError | InternalError):
        return False
    sqlstate = getattr(error.__cause__, "sqlstate", None)
    if isinstance(sqlstate, str) and (
        sqlstate.startswith(_TRANSIENT_SQLSTATE_PREFIXES) or sqlstate in _TRANSIENT_SQLSTATES
    ):
        return True
    message = str(error)
    return any(marker in message for marker in _TRANSIENT_DB_ERROR_MARKERS)


def is_dropped_connection_error(error: BaseException) -> bool:
    """Whether `error` is a connection that died mid-query, rather than any transient failure.

    Narrower than `is_transient_db_error` on purpose: a caller that retries immediately, with no
    backoff, must not retry a saturated pool or a restarting server straight back into the same
    failure.
    """
    if not isinstance(error, OperationalError | InterfaceError):
        return False
    message = str(error)
    return any(marker in message for marker in _DROPPED_CONNECTION_MARKERS)
