from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # `AddIndexConcurrently` requires atomic=False. Lives in its own migration per
    # PostHog policy (don't mix CONCURRENTLY operations with regular DDL).
    atomic = False
    dependencies = [("posthog", "1158_drop_property_type_not_null")]

    operations = [
        AddIndexConcurrently(
            model_name="materializedcolumnslot",
            index=models.Index(fields=["team", "slot_index"], name="posthog_mat_team_sl_idx"),
        ),
    ]
