from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1331_messagingrecord_campaign_key_idx"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="asyncdeletion",
            index=models.Index(
                name="asyncdeletion_team_type_idx",
                fields=["team_id", "deletion_type", "-created_at"],
            ),
        ),
    ]
