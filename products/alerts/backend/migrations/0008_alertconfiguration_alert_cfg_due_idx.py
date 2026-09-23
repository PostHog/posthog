from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("alerts", "0007_platformalertconfiguration_platformalert_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="alertconfiguration",
            index=models.Index(
                fields=["next_check_at", "id"],
                name="alert_cfg_due_idx",
                condition=models.Q(enabled=True),
            ),
        ),
    ]
