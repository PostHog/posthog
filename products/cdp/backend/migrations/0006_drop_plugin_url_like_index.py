from django.db import migrations

from posthog.migration_helpers import DropFieldIndexesConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("cdp", "0005_repair_hogfunction_batch_export_id_index"),
    ]

    operations = [
        DropFieldIndexesConcurrently(model_name="plugin", name="url"),
    ]
