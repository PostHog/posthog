from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0052_backfill_report_run_index_columns"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluationreportrun",
            index=models.Index(
                fields=["report", "-period_end"],
                name="llma_report_run_period_idx",
            ),
        ),
    ]
