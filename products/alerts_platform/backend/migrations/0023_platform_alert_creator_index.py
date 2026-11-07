from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("alerts_platform", "0022_platform_alert_creator_and_first_enabled"),
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
