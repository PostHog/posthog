# Generated manually to drop persons-related tables from main database
# This forces all Person model operations to use the database router
# which routes to the persons_db_writer database with the partitioned tables

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0905_alter_person_table"),
    ]

    operations = [
        # Drop all persons-related tables from main database
        # These will exist in the persons_db_writer database via Rust migrations
        # Drop in correct order: dependent tables first, then referenced tables
        migrations.RunSQL(
            sql="""
                DROP TABLE IF EXISTS posthog_cohortpeople;
                DROP TABLE IF EXISTS posthog_featureflaghashkeyoverride;
                DROP TABLE IF EXISTS posthog_group;
                DROP TABLE IF EXISTS posthog_grouptypemapping;
                DROP TABLE IF EXISTS posthog_persondistinctid;
                DROP TABLE IF EXISTS posthog_personlessdistinctid;
                DROP TABLE IF EXISTS posthog_personoverride;
                DROP TABLE IF EXISTS posthog_pendingpersonoverride;
                DROP TABLE IF EXISTS posthog_flatpersonoverride;
                DROP TABLE IF EXISTS posthog_personoverridemapping;
                DROP TABLE IF EXISTS posthog_person;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
