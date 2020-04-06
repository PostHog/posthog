from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0038_migrate_actions_to_precalculate_events'),
    ]

    operations = [
        # migrations.RunPython(migrate_event_ip_to_property, rollback),
        migrations.RunSQL(
            """
            UPDATE "posthog_event"
            SET properties = properties || jsonb_build_object('$ip', ip)
            WHERE ip IS NOT NULL;
            """,
            """
            UPDATE "posthog_event" 
            SET properties = properties - '$ip'
            """
        )
    ]