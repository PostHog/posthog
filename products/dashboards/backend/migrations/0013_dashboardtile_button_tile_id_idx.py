import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("dashboards", "0012_alter_dashboardtemplate_scope"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="dashboardtile",
                    name="button_tile",
                    field=models.ForeignKey(
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dashboard_tiles",
                        to="dashboards.buttontile",
                    ),
                ),
            ],
        ),
        CreateIndexConcurrently(
            index_name="posthog_dashboardtile_button_tile_id_idx",
            table_name="posthog_dashboardtile",
            columns='("button_tile_id")',
            where='WHERE "button_tile_id" IS NOT NULL',
        ),
    ]
