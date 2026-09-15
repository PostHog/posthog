from django.db import migrations, models
from django.db.models import Q

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
                fields=["team_id", "id"],
                name="posthog_action_webhook_idx",
                condition=Q(post_to_slack=True, deleted=False),
            ),
        ),
    ]
