from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1408_file_system_team_name_trgm_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(
                fields=["team_id", "user", "-created_at"],
                name="idx_alog_team_user_created_at",
            ),
        ),
    ]
