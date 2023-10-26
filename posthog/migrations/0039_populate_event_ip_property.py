from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0038_migrate_actions_to_precalculate_events"),
    ]

    operations = [
        migrations.RunSQL(
            """
            UPDATE "posthog_event"
            SET properties = properties || jsonb_build_object('$ip', ip)
            WHERE ip IS NOT NULL;
            """,
            "",
            elidable=True,  # This table no longer exists
        )
    ]
