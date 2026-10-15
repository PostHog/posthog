from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0005_repair_hogfunction_batch_export_id_index"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="pluginconfig",
            name="posthog_plu_enabled_f5ed94_idx",
        ),
    ]
