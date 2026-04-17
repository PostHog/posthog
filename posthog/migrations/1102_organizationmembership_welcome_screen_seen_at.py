from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1101_activitylog_client"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmembership",
            name="welcome_screen_seen_at",
            field=models.DateTimeField(blank=True, default=None, null=True),
        ),
    ]
