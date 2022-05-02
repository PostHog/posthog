# Generated by Django 3.2.12 on 2022-05-02 15:16

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0229_add_filters_hash_to_dashboard_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="person_display_name_properties",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=400),
                blank=True,
                default=["email", "name", "username"],
                null=True,
                size=None,
            ),
        ),
    ]
