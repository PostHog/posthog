import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("batch_exports", "0006_alter_batchexport_team_and_more"),
    ]

    operations = [
        # Django's automatic ForeignKey indexes on `source_id`. The only reader traverses
        # the FK forward, which resolves on the source table's primary key. The SET_NULL
        # cascade filters on `source_id`, but it runs only when a team is deleted, so both
        # indexes cost more in write-time maintenance and disk than they save.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="batchexport",
                    name="source",
                    field=models.ForeignKey(
                        blank=True,
                        db_index=False,
                        help_text="The source of the data to export. When set, takes precedence over `model`.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="batch_exports.batchexportsource",
                    ),
                ),
                migrations.AlterField(
                    model_name="batchexportondemand",
                    name="source",
                    field=models.ForeignKey(
                        blank=True,
                        db_index=False,
                        help_text="The source of the data to export. When set, takes precedence over `model`.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="batch_exports.batchexportsource",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_batchexport_source_id_157abc91",
                    table_name="posthog_batchexport",
                    columns="(source_id)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_batchexportondemand_source_id_af4fb4a7",
                    table_name="posthog_batchexportondemand",
                    columns="(source_id)",
                ),
            ],
        ),
    ]
