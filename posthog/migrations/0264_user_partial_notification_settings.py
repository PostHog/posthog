# Generated by Django 3.2.15 on 2022-10-04 15:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0263_plugin_config_web_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="partial_notification_settings",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
