# Generated by Django 3.2.5 on 2022-02-18 17:33

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ee", "0010_migrate_definitions_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=32), blank=True, default=list, null=True, size=None
            ),
        ),
        migrations.AddField(
            model_name="enterprisepropertydefinition",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=32), blank=True, default=list, null=True, size=None
            ),
        ),
    ]
