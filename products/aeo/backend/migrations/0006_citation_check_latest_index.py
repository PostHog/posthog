from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0005_team_config_and_brand_detection"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "prompt_id", "engine", "-created_at"],
                name="aeo_check_latest_engine_idx",
            ),
        ),
    ]
