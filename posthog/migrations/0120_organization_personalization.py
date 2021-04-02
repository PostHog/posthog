# Generated by Django 3.0.11 on 2021-01-29 09:24

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0119_mandatory_plugin_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="personalization",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=dict),
        ),
    ]
