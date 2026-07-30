from django.db import InterfaceError, OperationalError

# Substrings identifying transient Postgres failures. pgbouncer kills queries that wait too long
# for a backend connection with `query_wait_timeout`, and surfaces dropped/reset backend
# connections as connection failures. Both clear on their own, so a Temporal retry resolves them.
_TRANSIENT_DB_ERROR_MARKERS = (
    "query_wait_timeout",
    "server closed the connection unexpectedly",
    "connection failed",
    "the database system is starting up",
    "could not connect to server",
)


def is_transient_db_error(error: BaseException) -> bool:
    if not isinstance(error, OperationalError | InterfaceError):
        return False
    message = str(error)
    return any(marker in message for marker in _TRANSIENT_DB_ERROR_MARKERS)
