from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0243_unpack_plugin_source_files"),
    ]

    operations = [
        migrations.RunSQL(
            "DROP FUNCTION IF EXISTS should_update_person_prop",
            reverse_sql="",
            elidable=True,  # Removed from previous migration 0173_should_update_person_props_function.py
        ),
    ]
