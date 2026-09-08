from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0066_drop_ticket_assigned_to_column"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="ticket",
            name="posthog_con_team_id_1d12a2_idx",
        ),
    ]
