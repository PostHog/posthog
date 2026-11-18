from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """The index behind the read API's page, built without locking writes out of the table."""

    atomic = False

    dependencies = [
        ("alerts_platform", "0001_initial"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="platformalertconfiguration",
            index=models.Index(
                fields=["team_id", "-created_at", "-id"],
                name="platform_alert_cfg_list_idx",
            ),
        ),
    ]
