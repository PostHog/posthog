from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0062_evaluationreportrun_period_end_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluation",
            index=models.Index(
                condition=models.Q(("directory__isnull", False)),
                fields=["directory"],
                name="llma_eval_directory_idx",
            ),
        ),
    ]
