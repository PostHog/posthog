from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0068_alter_emailchannelsetup_team_and_more"),
    ]

    operations = [
        # Add the indexes that carry the ticket_number tiebreaker first, then drop the two they
        # supersede: each old index is a prefix of its replacement, so coverage never drops.
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["team", "-updated_at", "-ticket_number"],
                name="posthog_con_team_upd_num_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["team", "status", "-updated_at", "-ticket_number"],
                name="posthog_con_status_upd_num_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="ticket",
            name="posthog_con_team_updated_idx",
        ),
        SafeRemoveIndexConcurrently(
            model_name="ticket",
            name="posthog_con_status_upd_idx",
        ),
    ]
