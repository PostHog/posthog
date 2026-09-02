from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("annotations", "0003_annotation_hidden_in_user_interface"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="annotation",
            index=models.Index(fields=["team", "-date_marker"], name="annotation_team_by_marker"),
        ),
        SafeAddIndexConcurrently(
            model_name="annotation",
            index=models.Index(fields=["organization", "scope", "-date_marker"], name="annotation_org_by_marker"),
        ),
    ]
