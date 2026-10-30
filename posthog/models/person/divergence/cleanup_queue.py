"""The persons Postgres cleanup queue, as the repair tools see it.

The cleanup drain (`posthog/dags/person_pg_cleanup_drain.py`) owns this table and hard-deletes the persons queued in
it. A person that still owns a live distinct id is stamped `blocked_at` and skipped for a retry window. The repair
tools move `blocked_at` only: they clear it once a repair removed what blocked the person, so the next drain run
retries it, or stamp it to hold the person while a repair waits on a ClickHouse publish.

The queue is not person data that personhog serves, so it is read and written here directly, as the drain does.
"""

from collections.abc import Sequence
from typing import Any

from posthog.persons_db import persons_db_connection

PG_CLEANUP_QUEUE_TABLE = "person_pg_cleanup_queue"


def set_blocked(team_id: int, person_uuids: Sequence[str], *, blocked: bool) -> int:
    """Stamp `blocked_at` now on the queued persons, or clear it, and return how many queue rows changed."""
    if not person_uuids:
        return 0
    with persons_db_connection(writer=True) as conn, conn.cursor() as cursor:
        cursor.execute(
            f"UPDATE {PG_CLEANUP_QUEUE_TABLE} SET blocked_at = {'now()' if blocked else 'NULL'} "
            "WHERE team_id = %s AND person_uuid = ANY(%s::uuid[])",
            [team_id, list(person_uuids)],
        )
        return cursor.rowcount


def queue_entries(team_id: int, person_uuids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Each queued person's row by uuid: when the sweep queued it, the version bound, and when the drain blocked it."""
    if not person_uuids:
        return {}
    with persons_db_connection(writer=False) as conn, conn.cursor() as cursor:
        cursor.execute(
            f"SELECT person_uuid::text, deleted_at, max_version, blocked_at FROM {PG_CLEANUP_QUEUE_TABLE} "
            "WHERE team_id = %s AND person_uuid = ANY(%s::uuid[])",
            [team_id, list(person_uuids)],
        )
        return {
            person_uuid: {
                "deleted_at": deleted_at.isoformat(),
                "max_version": max_version,
                "blocked_at": blocked_at.isoformat() if blocked_at else None,
            }
            for person_uuid, deleted_at, max_version, blocked_at in cursor.fetchall()
        }
