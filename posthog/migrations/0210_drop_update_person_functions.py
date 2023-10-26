# Generated by Django 3.2.5 on 2022-02-11 15:43

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0209_plugin_logs_disabled"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP FUNCTION IF EXISTS update_person_props, should_update_person_props",
            elidable=True,  # Removed from previous migration 0173_should_update_person_props_function.py
        ),
    ]
