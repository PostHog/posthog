from django.db import InterfaceError, OperationalError

# Substrings identifying transient Postgres failures. pgbouncer kills queries that wait too long
# for a backend connection with `query_wait_timeout`, and surfaces dropped/reset backend
# connections as closed or reset connections. Both clear on their own, so a Temporal retry
# resolves them. Deliberately excludes psycopg's generic "connection failed:" prefix, which
# covers every failed connect including persistent misconfiguration (bad credentials,
# nonexistent database, unresolvable host) that must keep reaching error tracking.
_TRANSIENT_DB_ERROR_MARKERS = (
    "query_wait_timeout",
    "server closed the connection unexpectedly",
    "connection reset by peer",
    # pgbouncer's report that the backend connection assigned to an in-flight query died before
    # answering. Same self-healing dropped-connection condition as the closed/reset markers above,
    # just detected by the pooler rather than by the client. psycopg raises it as ProtocolViolation
    # (SQLSTATE 08P01), which is too broad to whitelist by class because a genuine protocol
    # violation is a driver bug that must keep reaching error tracking, so match the message.
    "server conn crashed?",
    "the database system is starting up",
    "the database system is shutting down",
    # pgbouncer's server_login_retry cooldown: a backend connect attempt failed, so pgbouncer
    # caches the failure and hands it to every client asking for a connection until the cooldown
    # (default 15s) elapses and it retries the backend itself. Self-heals without our retry doing
    # anything special, so it's transient by construction, not a symptom of the underlying cause.
    "server login has been failing, cached error",
    # psycopg's own message when libpq finds the backend socket already gone (raised as a
    # ProtocolViolation, SQLSTATE 08P01, which the class-based check above doesn't cover since
    # 08P01 also covers genuine protocol bugs). Same dead-socket condition as the "closed
    # unexpectedly" marker above, just detected client-side instead of reported by the server.
    # Reaches us standalone too, not only wrapped in the cached-login message above.
    "server conn crashed",
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


def is_transient_db_error(error: BaseException) -> bool:
    if not isinstance(error, OperationalError | InterfaceError):
        return False
    sqlstate = getattr(error.__cause__, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate.startswith(_TRANSIENT_SQLSTATE_PREFIXES):
        return True
    message = str(error)
    return any(marker in message for marker in _TRANSIENT_DB_ERROR_MARKERS)
