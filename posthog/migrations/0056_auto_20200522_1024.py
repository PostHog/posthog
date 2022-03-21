# Generated by Django 3.0.5 on 2020-05-22 10:24

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0055_user_anonymize_data"),
    ]

    operations = [
        migrations.AddField(model_name="action", name="is_calculating", field=models.BooleanField(default=False),),
        migrations.AddField(
            model_name="actionstep",
            name="properties",
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, null=True),
        ),
    ]
