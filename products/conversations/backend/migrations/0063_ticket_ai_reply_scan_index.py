from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0062_emailthreadaccountlink"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["last_message_at", "created_at"],
                name="posthog_con_ai_reply_scan_idx",
                condition=models.Q(status__in=["new", "open"]),
            ),
        ),
    ]
