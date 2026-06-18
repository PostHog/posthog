from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1099_subscription_delivery"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="summary_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="subscription",
            name="summary_prompt_guide",
            field=models.CharField(max_length=500, blank=True, default=""),
        ),
    ]
