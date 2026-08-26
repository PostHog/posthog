from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("conversations", "0053_ticket_sla_snooze_desc_indexes"),
    ]

    operations = [
        # Add the ascending expression indexes first so (team_id, sla_due_at) / (team_id,
        # snoozed_until) lookups keep index coverage throughout, then drop the now-redundant
        # plain single-column indexes they supersede.
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                models.F("team_id"),
                models.F("sla_due_at").asc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_sla_asc_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                models.F("team_id"),
                models.F("snoozed_until").asc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_snooze_asc_idx",
            ),
        ),
        SafeRemoveIndexConcurrently(
            model_name="ticket",
            name="posthog_con_team_sla_idx",
        ),
        SafeRemoveIndexConcurrently(
            model_name="ticket",
            name="posthog_con_team_snooze_idx",
        ),
    ]
