from django.db import migrations


class Migration(migrations.Migration):
    """
    Add a btree index on DashboardTile.team_id concurrently.

    HogQL queries against system.dashboard_tiles inject `WHERE team_id = X`,
    so the index is required for acceptable query latency on a fully-populated
    table. CREATE INDEX CONCURRENTLY needs atomic=False.

    The model carries db_index=False on the FK so Django's state has no
    matching index entry — this RunSQL is intentionally outside Django's
    state tracking (it lives only on the database side). Future makemigrations
    runs won't see drift because the field declares no index.
    """

    atomic = False

    dependencies = [
        ("dashboards", "0003_backfill_dashboardtile_team_id"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                '"posthog_dashboardtile_team_id_idx" '
                'ON "posthog_dashboardtile" ("team_id")'
            ),
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS "posthog_dashboardtile_team_id_idx"',
        ),
    ]
