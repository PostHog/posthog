from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("aeo", "0008_brand_catalog"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="aeocitationcheck",
            index=models.Index(
                fields=["team_id", "run_id"],
                name="aeo_check_team_run_idx",
            ),
        ),
    ]
