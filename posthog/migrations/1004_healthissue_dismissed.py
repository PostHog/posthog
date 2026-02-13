from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1003_clean_up_stale_alert_subscriptions"),
    ]

    operations = [
        migrations.AddField(
            model_name="healthissue",
            name="dismissed",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="healthissue",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("resolved", "Resolved"),
                ],
                default="active",
                max_length=20,
            ),
        ),
    ]
