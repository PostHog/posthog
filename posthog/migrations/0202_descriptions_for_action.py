# Generated by Django 3.2.5 on 2022-01-31 22:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0201_remove_property_type_format_constraint"),
    ]

    operations = [
        migrations.AddField(model_name="action", name="description", field=models.TextField(blank=True),),
    ]
