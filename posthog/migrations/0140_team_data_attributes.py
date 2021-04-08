# Generated by Django 3.0.11 on 2021-03-26 05:34

import django.contrib.postgres.fields
from django.db import migrations, models


def set_default_data_attributes(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    Team.objects.update(data_attributes=["data-attr"])


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0139_dashboard_tagging"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="data_attributes",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=["data-attr"]),
        ),
    ]
