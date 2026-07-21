from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0051_ticketalertrule_ticketincident_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["team", "created_at"], name="posthog_con_team_created_idx"),
        ),
    ]
