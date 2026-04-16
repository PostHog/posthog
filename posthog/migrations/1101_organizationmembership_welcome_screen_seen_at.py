from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1100_add_subscription_summary_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmembership",
            name="welcome_screen_seen_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
