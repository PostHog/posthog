from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0076_tag_legacy_conversation_attachments"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="conversationinboundevent",
            index=models.Index(
                fields=["team", "ticket_id"],
                name="conv_inbound_ticket_idx",
                condition=models.Q(ticket_id__isnull=False),
            ),
        ),
    ]
