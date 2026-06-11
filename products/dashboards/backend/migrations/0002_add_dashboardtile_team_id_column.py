import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add DashboardTile.team_id as a nullable FK with NOT VALID.

    Three-phase rollout:
      1. This migration adds the column NULL (backfill in 0003).
      2. 0003 backfills team_id from dashboard.team_id in batches.
      3. 0004 (in a later PR) flips the column to NOT NULL and registers
         the table as system.dashboard_tiles in HogQL.

    NOT VALID skips the historical-row check on the FK so this migration does
    not table-scan posthog_dashboardtile. Every pre-existing row is NULL after
    this step — Postgres still enforces the FK for all new writes.

    No CREATE INDEX here; the FK btree is added concurrently in a later
    migration (alongside the NOT NULL flip) so the index build does not lock
    the table.
    """

    dependencies = [
        ("dashboards", "0001_migrate_dashboards_models"),
        ("posthog", "1162_drop_hourly_from_subscription_frequency_choices"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="dashboardtile",
                    name="team",
                    field=models.ForeignKey(
                        null=True,
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "posthog_dashboardtile" '
                        'ADD COLUMN IF NOT EXISTS "team_id" integer NULL; '
                        'ALTER TABLE "posthog_dashboardtile" '
                        'ADD CONSTRAINT "posthog_dashboardtile_team_id_fkey" '
                        'FOREIGN KEY ("team_id") REFERENCES "posthog_team"("id") '
                        "ON DELETE CASCADE NOT VALID"
                    ),
                    reverse_sql=(
                        'ALTER TABLE "posthog_dashboardtile" '
                        'DROP CONSTRAINT IF EXISTS "posthog_dashboardtile_team_id_fkey"; '
                        'ALTER TABLE "posthog_dashboardtile" DROP COLUMN IF EXISTS "team_id"'
                    ),
                ),
            ],
        ),
    ]
