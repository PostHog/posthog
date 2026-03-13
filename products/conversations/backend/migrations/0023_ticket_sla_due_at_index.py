from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0022_ticket_sla_due_at"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["team", "sla_due_at"], name="posthog_con_team_sla_idx"),
        ),
    ]
