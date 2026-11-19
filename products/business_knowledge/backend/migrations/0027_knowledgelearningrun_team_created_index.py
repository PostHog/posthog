from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0026_team_bk_config_learning_backfill"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="knowledgelearningrun",
            index=models.Index(
                fields=["team", "analysis_version", "created_at"],
                name="bk_learn_run_team_created",
            ),
        ),
    ]
