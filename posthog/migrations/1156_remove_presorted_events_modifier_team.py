from django.db import migrations


def remove_presorted_events_modifier_from_teams(apps, schema_editor):
    """
    Remove the deprecated `usePresortedEventsTable` modifier from
    `posthog_team.modifiers`. Sister migration to 0999, which only scrubbed
    `posthog_dashboarditem.query` and `query.source`.

    The field was removed from `HogQLQueryModifiers` (which is `extra='forbid'`)
    in #46714, so any leftover team-level default still emits the key, which
    fails `QueryRequest` validation on every analytics query for that team.

    Uses PostgreSQL's `#-` JSON operator so the update is atomic and safe
    against concurrent edits. The `?` predicate restricts the rewrite to rows
    that actually contain the key.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            UPDATE posthog_team
            SET modifiers = modifiers #- '{usePresortedEventsTable}'
            WHERE modifiers ? 'usePresortedEventsTable'
        """)


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1155_sharingconfiguration_interviewee_context"),
    ]

    operations = [
        migrations.RunPython(
            remove_presorted_events_modifier_from_teams,
            reverse_noop,
        ),
    ]
