from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0067_ticket_archived_at"),
    ]

    operations = [
        # Partial: only archived tickets are in it, which is the list that has no other
        # index to fall back on. Every other query filters archived_at IS NULL, which
        # matches nearly every row and stays on the existing indexes.
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["team", "-updated_at"],
                name="posthog_con_archived_idx",
                condition=models.Q(archived_at__isnull=False),
            ),
        ),
    ]
