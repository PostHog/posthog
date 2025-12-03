# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0929_remove_legacy_batch_export_notification_setting"),
    ]

    operations = [
        migrations.AddField(
            model_name="alertconfiguration",
            name="detectors",
            field=models.JSONField(
                blank=True,
                null=True,
                default=None,
                help_text="Alert detectors configuration with AND/OR logic. When set, replaces threshold/condition.",
            ),
        ),
    ]
