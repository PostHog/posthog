# Generated by Django 2.2.7 on 2020-01-25 19:13

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0005_remove_person_distinct_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="distinct_ids",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(blank=True, max_length=400), blank=True, null=True, size=None,
            ),
        ),
    ]
