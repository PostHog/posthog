"""Self-healing lock guard for the teardown flush of test databases.

TRUNCATE needs an ACCESS EXCLUSIVE lock on every flushed table, so a single leaked
idle-in-transaction session (e.g. a background worker thread that never closed its
transaction) blocks teardown forever and the CI job dies at its timeout with no
diagnostics. Instead: time out quickly, name and terminate the blockers, retry once.

Wired into Django's flush command by posthog/conftest.py, which also reports
self-heal events (``reports``) at the end of the run.
"""

import logging
import warnings
from collections.abc import Callable

from django.db import connections

from psycopg import errors as psycopg_errors

logger = logging.getLogger(__name__)

# How long a teardown flush may wait on a Postgres lock before we terminate
# idle-in-transaction blockers and retry. Generous: nothing legitimate holds a table lock
# for anywhere near this long in tests.
FLUSH_LOCK_TIMEOUT_SECONDS = 30

# Self-heal events surfaced at the end of the run: pytest.ini ships `-p no:warnings`, so
# warnings.warn alone would be invisible in CI for passing tests.
reports: list[str] = []


def _is_lock_timeout(exc: BaseException | None) -> bool:
    # Walk both __cause__ and __context__: Django/management wrapping usually chains via
    # __cause__, but a LockNotAvailable can sit on __context__ when both are set.
    stack = [exc] if exc is not None else []
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, psycopg_errors.LockNotAvailable):
            return True
        stack.extend(linked for linked in (current.__cause__, current.__context__) if linked is not None)
    return False


def _snapshot_sessions(database: str) -> tuple[list[str], list[int]]:
    """Describe other sessions on this connection's database (any state, for diagnostics —
    an *active* blocker should still be named even though we never kill it) and identify
    the leaked ones: idle in transaction since before our lock wait began, so provably
    the blocker. A session merely *between* statements of an in-flight transaction
    (idle-in-transaction for milliseconds, e.g. a concurrent background thread mid-INSERT)
    is not considered leaked.
    """
    with connections[database].cursor() as cursor:
        cursor.execute(
            """
            SELECT pid, usename, application_name, state, wait_event_type, wait_event,
                   now() - xact_start AS xact_age,
                   now() - state_change AS state_age,
                   COALESCE(state_change < now() - make_interval(secs => %s), FALSE) AS stale,
                   query
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid != pg_backend_pid()
              AND backend_type = 'client backend'
            """,
            [FLUSH_LOCK_TIMEOUT_SECONDS],
        )
        sessions = cursor.fetchall()
    descriptions = [
        f"pid={pid} user={user} app={app!r} state={state!r} wait_event={wait_type}/{wait_event} "
        f"xact_age={xact_age} state_age={state_age} last_query={query!r}"
        for pid, user, app, state, wait_type, wait_event, xact_age, state_age, _stale, query in sessions
    ]
    leaked_pids = [row[0] for row in sessions if row[3] and row[3].startswith("idle in transaction") and row[8]]
    return descriptions, leaked_pids


def _terminate_leaked_sessions(database: str) -> tuple[list[str], int]:
    descriptions, leaked_pids = _snapshot_sessions(database)
    if leaked_pids:
        with connections[database].cursor() as cursor:
            cursor.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid = ANY(%s)", [leaked_pids])
    return descriptions, len(leaked_pids)


def flush_with_lock_guard(database: str, flush: Callable[[], None]) -> None:
    """Run a teardown flush with a session lock_timeout and a terminate-and-retry fallback."""
    conn = connections[database]
    with conn.cursor() as cursor:
        cursor.execute("SELECT set_config('lock_timeout', %s, false)", [f"{FLUSH_LOCK_TIMEOUT_SECONDS}s"])
    try:
        flush()
    except Exception as err:
        if not _is_lock_timeout(err):
            raise
        sessions, terminated = _terminate_leaked_sessions(database)
        sessions_desc = "; ".join(sessions)
        message = (
            f"Teardown flush of {database!r} timed out after {FLUSH_LOCK_TIMEOUT_SECONDS}s waiting for a "
            f"table lock; terminated {terminated} idle-in-transaction session(s) of {len(sessions)} on the "
            f"database, retrying once: {sessions_desc}"
        )
        logger.exception(message)
        warnings.warn(message, stacklevel=2)
        reports.append(message)
        try:
            flush()
        except Exception as retry_err:
            try:
                current_sessions, _ = _snapshot_sessions(database)
            except Exception:
                current_sessions = ["<snapshot unavailable>"]
            raise RuntimeError(
                f"Teardown flush of {database!r} failed again after terminating {terminated} "
                f"idle-in-transaction session(s); sessions now: {'; '.join(current_sessions)} | "
                f"at first failure: {sessions_desc}"
            ) from retry_err
    finally:
        try:
            with conn.cursor() as cursor:
                cursor.execute("RESET lock_timeout")
        except Exception:
            # The flush may have failed because the connection itself died; raising here
            # would mask that original error, and a reconnect gets fresh session state anyway.
            logger.warning("Could not reset lock_timeout after flushing %r", database, exc_info=True)
