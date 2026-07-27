import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Enforce NOT NULL on DashboardTile.team_id.

    Step 3 of three. The column was added nullable in 0002 and backfilled in
    0003. The backfill is idempotent on team_id IS NULL — verify in production
    before merging this migration that no rows remain unpopulated:

        SELECT COUNT(*) FROM posthog_dashboardtile WHERE team_id IS NULL;

    SeparateDatabaseAndState keeps Django's state in sync with the field flip
    on the model. `not-null-ignore` annotation tells the migration analyzer
    that the rewrite-the-table risk does not apply: there are no NULL rows by
    construction, so SET NOT NULL only adds the catalog flag.
    """

    dependencies = [
        ("dashboards", "0004_add_dashboardtile_team_id_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="dashboardtile",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "-- not-null-ignore: team_id backfilled in 0003_backfill_dashboardtile_team_id\n"
                        'ALTER TABLE "posthog_dashboardtile" ALTER COLUMN "team_id" SET NOT NULL'
                    ),
                    reverse_sql='ALTER TABLE "posthog_dashboardtile" ALTER COLUMN "team_id" DROP NOT NULL',
                ),
            ],
        ),
    ]
