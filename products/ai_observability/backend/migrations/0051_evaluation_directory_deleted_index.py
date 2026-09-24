from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0050_alter_evaluationreportrun_options"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluation",
            index=models.Index(
                fields=["directory", "deleted"],
                name="llma_eval_dir_deleted_idx",
            ),
        ),
    ]
