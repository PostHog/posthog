from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1306_add_youtube_analytics_integration_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="tasks_pr_loop_enabled",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
