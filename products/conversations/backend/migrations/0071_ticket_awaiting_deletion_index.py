from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0070_ticket_awaiting_deletion"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["awaiting_deletion_id"],
                name="posthog_con_await_del_idx",
                condition=models.Q(awaiting_deletion_id__isnull=False),
            ),
        ),
    ]
