from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("batch_exports", "0010_alter_batchexportdestination_type"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="batchexportrun",
            index=models.Index(fields=["batch_export", "-data_interval_end"], name="batchexportrun_export_end_idx"),
        ),
    ]
