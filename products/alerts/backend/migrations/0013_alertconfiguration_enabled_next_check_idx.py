from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("alerts", "0012_move_platform_models_to_alerts_platform"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="alertconfiguration",
            index=models.Index(
                fields=["next_check_at"],
                name="alert_enabled_next_check_idx",
                condition=models.Q(enabled=True),
            ),
        ),
    ]
