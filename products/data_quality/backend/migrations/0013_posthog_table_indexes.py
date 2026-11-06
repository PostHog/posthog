from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_quality", "0012_posthog_table_subject")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="dataqualitycheck",
            index=models.Index(
                fields=["team", "posthog_table"],
                condition=~models.Q(posthog_table=""),
                name="quality_check_ph_table_idx",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_quality_check_fp_posthog_table",
                    table_name="data_quality_dataqualitycheck",
                    columns="(team_id, posthog_table, fingerprint)",
                    unique=True,
                    where="WHERE posthog_table <> '' AND (NOT deleted OR deleted IS NULL)",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="dataqualitycheck",
                    constraint=models.UniqueConstraint(
                        condition=~models.Q(posthog_table="")
                        & (models.Q(deleted=False) | models.Q(deleted__isnull=True)),
                        fields=("team", "posthog_table", "fingerprint"),
                        name="unique_quality_check_fp_posthog_table",
                    ),
                ),
            ],
        ),
    ]
