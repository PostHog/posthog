# Generated by Django 4.2.18 on 2025-02-26 16:27

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0676_team_session_recording_masking_config"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="team",
            options={"verbose_name": "environment (aka team)", "verbose_name_plural": "environments (aka teams)"},
        ),
    ]
