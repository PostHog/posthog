# Generated manually - Drops the old TeamCoreEventsConfig table
# This is the second step after migration 0957 removed the model from Django state

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0957_refactor_core_events_to_table"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS posthog_teamcoreeventsconfig;",
            reverse_sql="",  # No reverse - table is obsolete
        ),
    ]
