from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1329_drop_cimd_metadata_url"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="messagingrecord",
            index=models.Index(fields=["campaign_key"], name="messagingrecord_campaign_idx"),
        ),
    ]
