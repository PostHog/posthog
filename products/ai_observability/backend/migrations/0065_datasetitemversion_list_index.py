from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ai_observability", "0064_backfill_execution_outcomes"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datasetitemversion",
            index=models.Index(
                fields=["team", "dataset", "archived"],
                name="llma_ds_item_ver_v2_list_idx",
            ),
        ),
    ]
