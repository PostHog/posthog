from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0048_evaluationbackfill"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluationreport",
            index=models.Index(
                fields=["team", "id"],
                name="llma_rep_team_sched_idx",
                condition=models.Q(
                    enabled=True,
                    deleted=False,
                    frequency="scheduled",
                    next_delivery_date__isnull=False,
                ),
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="evaluationreport",
            index=models.Index(
                fields=["next_delivery_date", "id"],
                name="llma_rep_sched_due_idx",
                condition=models.Q(
                    enabled=True,
                    deleted=False,
                    frequency="scheduled",
                    next_delivery_date__isnull=False,
                ),
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="evaluationreport",
            index=models.Index(
                fields=["team", "id"],
                name="llma_rep_team_count_idx",
                condition=models.Q(
                    enabled=True,
                    deleted=False,
                    frequency="every_n",
                    trigger_threshold__isnull=False,
                ),
            ),
        ),
    ]
