from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1042_subscription_integration_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="batchexport",
            name="interval",
            field=models.CharField(
                choices=[
                    ("hour", "hour"),
                    ("day", "day"),
                    ("week", "week"),
                    ("every 5 minutes", "every 5 minutes"),
                    ("every 15 minutes", "every 15 minutes"),
                ],
                default="hour",
                help_text="The interval at which to export data.",
                max_length=64,
            ),
        ),
    ]
