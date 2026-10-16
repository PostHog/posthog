from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0061_backfill_condition_ids"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluationreportrun",
            index=models.Index(
                fields=["report", "-period_end"],
                name="llma_eval_run_period_end_idx",
            ),
        ),
    ]
