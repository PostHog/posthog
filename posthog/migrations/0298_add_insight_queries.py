# Generated by Django 3.2.16 on 2023-01-28 15:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0297_property_definitions_index_query"),
    ]

    operations = [
        migrations.AddField(
            model_name="insight",
            name="query",
            field=models.JSONField(null=True),
        ),
    ]
