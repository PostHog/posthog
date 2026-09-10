from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently, SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("data_quality", "0010_validate_metric_subject_binding")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                CreateIndexConcurrently(
                    index_name="unique_quality_check_fp_metric",
                    table_name="data_quality_dataqualitycheck",
                    columns="(team_id, metric_id, fingerprint)",
                    unique=True,
                    where="WHERE metric_id IS NOT NULL AND (NOT deleted OR deleted IS NULL)",
                ),
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="dataqualitycheck",
                    constraint=models.UniqueConstraint(
                        condition=models.Q(metric__isnull=False)
                        & (models.Q(deleted=False) | models.Q(deleted__isnull=True)),
                        fields=("team", "metric", "fingerprint"),
                        name="unique_quality_check_fp_metric",
                    ),
                ),
            ],
        ),
        SafeAddIndexConcurrently(
            model_name="dataqualitycheck",
            index=models.Index(
                fields=["team", "metric"], condition=models.Q(metric__isnull=False), name="quality_check_metric_idx"
            ),
        ),
    ]
