from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0072_ticket_soft_delete"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["deleted_at"],
                name="posthog_con_ticket_deleted_idx",
                condition=models.Q(deleted_at__isnull=False),
            ),
        ),
    ]
