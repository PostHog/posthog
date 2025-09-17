from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0837_alter_externaldatasource_source_type"),
    ]

    operations = [
        migrations.RunSQL(
            # Remove null values from existing app_urls arrays
            """
            UPDATE posthog_team
            SET app_urls = array_remove(app_urls, NULL)
            WHERE array_position(app_urls, NULL) IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            # Remove null values from existing recording_domains arrays
            """
            UPDATE posthog_team
            SET recording_domains = array_remove(recording_domains, NULL)
            WHERE recording_domains IS NOT NULL AND array_position(recording_domains, NULL) IS NOT NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
