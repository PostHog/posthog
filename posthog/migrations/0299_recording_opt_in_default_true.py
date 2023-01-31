# Generated by Django 3.2.16 on 2023-01-31 17:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0298_add_insight_queries"),
    ]

    operations = [
        migrations.AlterField(
            model_name="team",
            name="capture_console_log_opt_in",
            field=models.BooleanField(blank=True, default=True, null=True),
        ),
        migrations.AlterField(
            model_name="team",
            name="session_recording_opt_in",
            field=models.BooleanField(default=True),
        ),
    ]
