# Generated by Django 3.0.6 on 2020-11-09 12:22

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0097_invite_emails"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="event_names_with_usage",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="team",
            name="event_properties_with_usage",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=list),
        ),
    ]
