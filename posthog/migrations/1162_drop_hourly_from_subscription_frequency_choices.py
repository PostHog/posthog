from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1161_remove_subscription_hourly_frequency")]

    operations = [
        migrations.AlterField(
            model_name="subscription",
            name="frequency",
            field=models.CharField(
                choices=[
                    ("daily", "Daily"),
                    ("weekly", "Weekly"),
                    ("monthly", "Monthly"),
                    ("yearly", "Yearly"),
                ],
                max_length=10,
            ),
        ),
    ]
