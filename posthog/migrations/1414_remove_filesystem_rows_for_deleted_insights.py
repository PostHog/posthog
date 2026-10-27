import logging

from django.db import OperationalError, migrations, transaction

logger = logging.getLogger(__name__)


def remove_rows(apps, schema_editor):
    connection = schema_editor.connection

    try:
        with transaction.atomic(using=connection.alias), connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute("SELECT DISTINCT team_id FROM posthog_dashboarditem WHERE deleted = true")
            team_ids = [row[0] for row in cur.fetchall()]
    except OperationalError:
        logger.warning("1414: could not list teams with deleted insights, skipping cleanup")
        return

    # A team that times out is skipped, never failed: stale rows are harmless and the cleanup is optional.
    for team_id in team_ids:
        try:
            with transaction.atomic(using=connection.alias), connection.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '15s'")
                cur.execute("SET LOCAL lock_timeout = '2s'")
                cur.execute(
                    "SELECT short_id FROM posthog_dashboarditem WHERE team_id = %s AND deleted = true",
                    [team_id],
                )
                short_ids = [row[0] for row in cur.fetchall()]
                for table in ("posthog_filesystem", "posthog_filesystemshortcut"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE team_id = %s AND type = 'insight' AND ref = ANY(%s)",
                        [team_id, short_ids],
                    )
        except OperationalError:
            logger.warning("1414: skipped team %s", team_id)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1413_event_filter_pipeline_override")]

    operations = [migrations.RunPython(remove_rows, migrations.RunPython.noop)]
