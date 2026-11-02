import logging

from django.db import OperationalError, migrations, transaction

logger = logging.getLogger(__name__)

ID_CHUNK = 500_000
MIN_SPLIT = 1_000
TEAM_TIMEOUTS = ("15s", "60s", "300s")


def _run(connection, timeout, fn):
    with transaction.atomic(using=connection.alias), connection.cursor() as cur:
        cur.execute(f"SET LOCAL statement_timeout = '{timeout}'")
        cur.execute("SET LOCAL lock_timeout = '2s'")
        return fn(cur)


def _teams_in_range(connection, lo, hi, found):
    def query(cur):
        cur.execute(
            "SELECT DISTINCT team_id FROM posthog_dashboarditem WHERE deleted = true AND id > %s AND id <= %s",
            [lo, hi],
        )
        return [row[0] for row in cur.fetchall()]

    try:
        found.update(_run(connection, "60s", query))
    except OperationalError:
        if hi - lo <= MIN_SPLIT:
            logger.warning("1414: could not scan insight ids %s to %s", lo, hi)
            return
        mid = (lo + hi) // 2
        _teams_in_range(connection, lo, mid, found)
        _teams_in_range(connection, mid, hi, found)


def _clean_team(connection, team_id, timeout):
    def work(cur):
        # The subquery runs inside the DELETE, so an insight restored after team discovery keeps its entry.
        for table in ("posthog_filesystem", "posthog_filesystemshortcut"):
            cur.execute(
                f"""
                DELETE FROM {table}
                WHERE team_id = %s AND type = 'insight'
                  AND ref IN (SELECT short_id FROM posthog_dashboarditem WHERE team_id = %s AND deleted = true)
                """,
                [team_id, team_id],
            )

    _run(connection, timeout, work)


def remove_rows(apps, schema_editor):
    connection = schema_editor.connection

    with connection.cursor() as cur:
        cur.execute("SELECT max(id) FROM posthog_dashboarditem")
        max_id = cur.fetchone()[0] or 0

    team_ids: set[int] = set()
    for lo in range(0, max_id, ID_CHUNK):
        _teams_in_range(connection, lo, min(lo + ID_CHUNK, max_id), team_ids)

    # A team that times out is retried with a longer timeout, never failed: the cleanup is optional.
    pending = sorted(team_ids)
    for timeout in TEAM_TIMEOUTS:
        still_pending = []
        for team_id in pending:
            try:
                _clean_team(connection, team_id, timeout)
            except OperationalError:
                still_pending.append(team_id)
        pending = still_pending
        if not pending:
            break

    for team_id in pending:
        logger.warning("1414: skipped team %s", team_id)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1413_event_filter_pipeline_override")]

    operations = [migrations.RunPython(remove_rows, migrations.RunPython.noop)]
