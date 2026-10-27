from django.db import migrations


def remove_rows(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT DISTINCT team_id FROM posthog_dashboarditem WHERE deleted = true")
        team_ids = [row[0] for row in cur.fetchall()]

        # One short statement per team: a single join across all teams is too slow on production data.
        for team_id in team_ids:
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


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("posthog", "1413_event_filter_pipeline_override")]

    operations = [migrations.RunPython(remove_rows, migrations.RunPython.noop)]
