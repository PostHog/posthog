from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("actions", "0002_alter_action_created_by_alter_action_events_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="action",
            index=models.Index(
                condition=models.Q(("deleted", False), ("post_to_slack", True)),
                fields=["id"],
                name="posthog_action_slack_idx",
            ),
        ),
    ]
