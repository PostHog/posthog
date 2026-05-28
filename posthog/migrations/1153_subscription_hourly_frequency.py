from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1152_fix_device_bucketing_persist_across_auth")]

    operations = [
        migrations.AlterField(
            model_name="subscription",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("hourly", "Hourly"),
                    ("daily", "Daily"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                    ("yearly", "Yearly"),
                ],
                max_length=10,
            ),
        ),
    ]
