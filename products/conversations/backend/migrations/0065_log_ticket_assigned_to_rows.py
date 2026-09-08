from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)


def log_surviving_assignments(apps, schema_editor) -> None:
    # 0013 replaced the field with TicketAssignment and copied nothing across, so any value
    # left here has been unreadable since. Record how much the next migration discards; the
    # count is expected to be zero and the deploy proceeds either way.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'SELECT count(*) FROM "posthog_conversations_ticket" WHERE "assigned_to_id" IS NOT NULL',
        )
        count = cursor.fetchone()[0]
    if count:
        logger.warning("conversations_ticket_assigned_to_discarded", rows=count)


class Migration(migrations.Migration):
    dependencies = [
        ("conversations", "0064_alter_emailthreadaccountlink_match_source"),
    ]

    operations = [
        migrations.RunPython(log_surviving_assignments, migrations.RunPython.noop, elidable=True),
    ]
