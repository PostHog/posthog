from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0032_ticket_snoozed_until"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["team", "snoozed_until"], name="posthog_con_team_snooze_idx"),
        ),
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["snoozed_until"],
                name="posthog_con_snooze_wake_idx",
                condition=models.Q(snoozed_until__isnull=False),
            ),
        ),
    ]
