import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import SafeAddIndexConcurrently


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
        SafeAddIndexConcurrently(
            model_name="dashboardtile",
            index=models.Index(
                fields=["button_tile"],
                name="posthog_dashboardtile_button_tile_id_idx",
                condition=Q(("button_tile__isnull", False)),
            ),
        ),
    ]
