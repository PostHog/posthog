from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1100_add_subscription_summary_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="client",
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
