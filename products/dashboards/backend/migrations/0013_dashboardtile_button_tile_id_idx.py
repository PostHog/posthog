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
        # `button_tile` was added (posthog migration 1059) with the FK's default db_index=True in
        # Django state, but the hand-written SQL that created the column never built the index — so
        # state expected a full FK index that production never had, and makemigrations couldn't see
        # the drift. Reconcile state to db_index=False (state-only: there is no DB index to drop),
        # then build the real lookup index concurrently. It's partial because button_tile_id is NULL
        # for every non-button tile, so the index only needs the button rows (mirrors `widget`).
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
