from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0052_ticket_organization_id_source"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                models.F("team_id"),
                models.F("sla_due_at").desc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_sla_desc_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                models.F("team_id"),
                models.F("snoozed_until").desc(nulls_last=True),
                models.F("ticket_number").desc(),
                name="posthog_con_snooze_desc_idx",
            ),
        ),
    ]
