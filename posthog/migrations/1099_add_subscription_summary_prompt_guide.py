from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1098_add_subscription_summary_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscription",
            name="summary_prompt_guide",
            field=models.CharField(max_length=500, blank=True, default=""),
        ),
    ]
