# Generated by Django 3.0.11 on 2021-03-26 05:34

import django.contrib.postgres.fields
from django.db import migrations, models


def set_default_data_attributes(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")
    Team.objects.update(important_data_attributes=["data-attr"])


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0138_featureflag_name_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="important_data_attributes",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=200, null=True), blank=True, default=list, size=None
            ),
        ),
        migrations.RunPython(set_default_data_attributes, migrations.RunPython.noop),
    ]
