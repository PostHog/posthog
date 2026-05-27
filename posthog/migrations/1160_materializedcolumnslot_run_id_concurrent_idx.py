from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # `AddIndexConcurrently` requires atomic=False. Lives in its own migration per
    # PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("posthog", "1159_materializedcolumnslot_team_slot_index_concurrent")]

    operations = [
        AddIndexConcurrently(
            model_name="materializedcolumnslot",
            index=models.Index(fields=["backfill_temporal_run_id"], name="posthog_mat_run_id_idx"),
        ),
    ]
