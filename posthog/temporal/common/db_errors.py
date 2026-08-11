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
    "the database system is starting up",
    "the database system is shutting down",
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
