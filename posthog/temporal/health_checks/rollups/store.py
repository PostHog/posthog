from __future__ import annotations

from collections.abc import Sequence

from django.db import connections, models

WRITE_DATABASE = "default"
DELETE_BATCH_SIZE = 10_000


def _delete_in_batches(table: str, condition: str, params: list[list[int]]) -> int:
    delete_sql = f"DELETE FROM {table} WHERE ctid = ANY(ARRAY(SELECT ctid FROM {table} WHERE {condition} LIMIT %s))"
    deleted = 0
    while True:
        with connections[WRITE_DATABASE].cursor() as cursor:
            cursor.execute(delete_sql, [*params, DELETE_BATCH_SIZE])
            batch = cursor.rowcount
        deleted += batch
        if batch < DELETE_BATCH_SIZE:
            return deleted


def delete_rollup_rows_for_teams(model: type[models.Model], team_ids: Sequence[int]) -> int:
    """Delete every row of the given environments. Team deletion calls this, because no foreign key cascades."""
    if not team_ids:
        return 0
    return _delete_in_batches(model._meta.db_table, "team_id = ANY(%s)", [list(team_ids)])
