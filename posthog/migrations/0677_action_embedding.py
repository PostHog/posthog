# Generated by Django 4.2.18 on 2025-02-28 19:09

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0676_action_last_summarized_at_action_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="action",
            name="embedding",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.FloatField(),
                blank=True,
                help_text="The vector embedding of the action",
                null=True,
                size=None,
            ),
        ),
    ]
