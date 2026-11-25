from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0016_citation_check_prompt_branded"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "created_at"],
                include=[
                    "id",
                    "mode",
                    "engine",
                    "prompt_id",
                    "prompt_topic",
                    "check_failed",
                    "cited",
                    "names_brand",
                    "prompt_branded",
                    "target_best_position",
                ],
                name="aeo_check_window_cover_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "prompt_id", "engine", "-created_at"],
                include=["id"],
                name="aeo_check_latest_idx",
            ),
        ),
    ]
