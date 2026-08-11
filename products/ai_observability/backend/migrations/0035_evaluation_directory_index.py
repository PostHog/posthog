from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0034_evaluationdirectory_evaluation_directory_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="evaluation",
            index=models.Index(
                fields=["team", "directory", "-created_at", "id"],
                name="llma_eval_team_dir_created_idx",
            ),
        ),
    ]
