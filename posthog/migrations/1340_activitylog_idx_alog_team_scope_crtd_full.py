from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("posthog", "1339_validate_taggeditem_project_fk"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="activitylog",
            index=models.Index(fields=["team_id", "scope", "-created_at"], name="idx_alog_team_scope_crtd_full"),
        ),
    ]
