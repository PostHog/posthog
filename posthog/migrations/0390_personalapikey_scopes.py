# Generated by Django 4.1.13 on 2024-02-14 12:55

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0389_alter_batchexportdestination_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="scoped_organizations",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=100), null=True, size=None
            ),
        ),
        migrations.AddField(
            model_name="personalapikey",
            name="scoped_teams",
            field=django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), null=True, size=None),
        ),
        migrations.AddField(
            model_name="personalapikey",
            name="scopes",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=100), null=True, size=None
            ),
        ),
    ]
