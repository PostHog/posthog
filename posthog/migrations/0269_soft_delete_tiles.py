# Generated by Django 3.2.15 on 2022-10-11 12:48

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0268_plugin_source_file_updated_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="dashboardtile",
            name="deleted",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
