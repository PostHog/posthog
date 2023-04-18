# Generated by Django 3.0.3 on 2020-03-18 14:59

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0034_pg_trgm_and_btree_20200318_1447"),
    ]

    operations = [
        # We used to create an index here, but realised that made things slower rather than faster
        migrations.RunSQL(
            "SELECT 1;",
            "DROP INDEX IF EXISTS posthog_event_properties_current_url_gin",
            elidable=True,  # This table no longer exists
        )
    ]
