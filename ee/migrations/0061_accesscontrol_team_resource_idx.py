from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY takes SHARE UPDATE EXCLUSIVE, so it blocks no reader and no writer, and
    # PostgreSQL cannot run it inside a transaction.
    atomic = False

    dependencies = [("ee", "0060_backfill_evaluation_access_control")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="accesscontrol",
            index=models.Index(fields=["team", "resource"], name="ee_accessc_team_resource_idx"),
        ),
    ]
