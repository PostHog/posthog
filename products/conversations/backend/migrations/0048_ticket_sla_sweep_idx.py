from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0047_ticket_sla_warning_fields"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["sla_due_at"],
                name="posthog_con_sla_sweep_idx",
                condition=models.Q(sla_due_at__isnull=False),
            ),
        ),
    ]
