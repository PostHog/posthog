from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    dependencies = [
        ("actions", "0001_migrate_actions_models"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="action",
            index=models.Index(
                condition=models.Q(("deleted", False)),
                fields=["team_id", "name"],
                name="action_team_name_not_deleted",
            ),
        ),
    ]
