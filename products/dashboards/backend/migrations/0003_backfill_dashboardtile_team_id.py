from django.db import migrations


def backfill_team_id(apps, schema_editor) -> None:
    """
    Backfill DashboardTile.team_id from dashboard.team_id in batches.

    The whole backfill runs in the migration's single transaction (Django's
    default `atomic = True`). Batching keeps individual `UPDATE` statements
    small — bounded memory, bounded statement runtime — rather than splitting
    the work into independent commits.

    Uses keyset pagination (`id__gt=last_id`) so each batch query only scans
    forward from the previous batch's last id. Without this, every iteration
    would re-walk the PK index from id=0 filtering `team_id IS NULL`, and since
    there is no partial index on that predicate the final batches would
    approach a full table scan.
    """
    DashboardTile = apps.get_model("dashboards", "DashboardTile")
    batch_size = 5000
    last_id = 0

    while True:
        batch_ids = list(
            DashboardTile.objects.filter(team_id__isnull=True, id__gt=last_id)
            .order_by("id")
            .values_list("id", flat=True)[:batch_size]
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

        last_id = batch_ids[-1]


class Migration(migrations.Migration):
    """
    Backfill DashboardTile.team_id (added nullable in 0002).

    Step 2 of three. Runs only `UPDATE`s; no schema changes. Decoupled from
    0002 so the column rollout and backfill can be deployed and verified
    independently — keep the backfill out of any release that also touches
    the column shape.
    """

    dependencies = [
        ("dashboards", "0002_add_dashboardtile_team_id_column"),
    ]

    operations = [
        migrations.RunPython(backfill_team_id, reverse_code=migrations.RunPython.noop),
    ]
