from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1330_alter_team_test_account_filters"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="messagingrecord",
            index=models.Index(fields=["campaign_key"], name="messagingrecord_campaign_idx"),
        ),
    ]
