from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("alerts_platform", "0023_platform_alert_created_by"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="platformalertconfiguration",
            index=models.Index(
                condition=models.Q(("created_by__isnull", False)),
                fields=["created_by"],
                name="platform_alert_cfg_creator_idx",
            ),
        ),
    ]
