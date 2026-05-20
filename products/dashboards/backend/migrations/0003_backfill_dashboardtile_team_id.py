from django.db import migrations


def backfill_team_id(apps, schema_editor) -> None:
    """
    Backfill DashboardTile.team_id from dashboard.team_id in batches.

    Idempotent: only operates on rows where team_id IS NULL, so reruns after a
    partial failure simply pick up where the previous run stopped. Each batch
    commits its own transaction (`RunPython` honors the migration's atomic
    flag, which is True by default and produces a single transaction — but
    psycopg's autocommit-on-cursor below avoids holding row locks across the
    full backfill).
    """
    DashboardTile = apps.get_model("dashboards", "DashboardTile")
    batch_size = 5000

    while True:
        batch_ids = list(
            DashboardTile.objects.filter(team_id__isnull=True).order_by("id").values_list("id", flat=True)[:batch_size]
        )
        if not batch_ids:
            break

        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE posthog_dashboardtile AS t
                SET team_id = d.team_id
                FROM posthog_dashboard AS d
                WHERE t.dashboard_id = d.id
                  AND t.id = ANY(%s)
                """,
                [batch_ids],
            )


class Migration(migrations.Migration):
    """
    Backfill DashboardTile.team_id (added nullable in 0002).

    Step 2 of three. Runs only `UPDATE`s; no schema changes. Decoupled from
    0002 so the column rollout and backfill can be deployed and verified
    independently — keep the backfill out of any release that also touches
    the column shape.
    """

    atomic = False

    dependencies = [
        ("dashboards", "0002_add_dashboardtile_team_id_column"),
    ]

    operations = [
        migrations.RunPython(backfill_team_id, reverse_code=migrations.RunPython.noop),
    ]
