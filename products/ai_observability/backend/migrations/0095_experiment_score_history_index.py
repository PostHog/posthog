from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("ai_observability", "0094_experiment_scorer_scope")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="offlineexperiment",
            index=models.Index(
                fields=["experiment_scorer_version", "team", "-started_at", "id"],
                condition=models.Q(experiment_scorer_version__isnull=False),
                name="aio_exp_score_history_idx",
            ),
        ),
    ]
