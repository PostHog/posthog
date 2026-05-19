from django.db import migrations


def remove_presorted_events_modifier(apps, schema_editor):
    """
    Remove the deprecated usePresortedEventsTable modifier from insight queries.
    Uses atomic PostgreSQL JSON operators to avoid race conditions with concurrent edits.
    """
    with schema_editor.connection.cursor() as cursor:
        # Remove from query->modifiers atomically
        cursor.execute("""
            UPDATE posthog_dashboarditem
            SET query = query #- '{modifiers,usePresortedEventsTable}'
            WHERE query->'modifiers' ? 'usePresortedEventsTable'
        """)

        # Remove from query->source->modifiers atomically
        cursor.execute("""
            UPDATE posthog_dashboarditem
            SET query = jsonb_set(
                query,
                '{source}',
                (query->'source') #- '{modifiers,usePresortedEventsTable}'
            )
            WHERE query->'source'->'modifiers' ? 'usePresortedEventsTable'
        """)


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0998_team_proactive_tasks_enabled"),
    ]

    operations = [
        migrations.RunPython(
            remove_presorted_events_modifier,
            reverse_noop,
        ),
    ]
