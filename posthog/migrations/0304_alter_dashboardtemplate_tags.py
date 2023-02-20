# Generated by Django 3.2.16 on 2023-02-20 13:06

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0303_auto_20230220_1306"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dashboardtemplate",
            name="tags",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255), blank=True, default=list, size=None
            ),
        ),
    ]
