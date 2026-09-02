from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("batch_exports", "0005_add_batch_export_source"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="batchexportrun",
            index=models.Index(
                condition=models.Q(("batch_export__isnull", False), ("records_completed__isnull", False)),
                fields=["batch_export", "status", "-data_interval_end"],
                name="be_run_export_completed_idx",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="batchexportrun",
            index=models.Index(
                condition=models.Q(("batch_export_on_demand__isnull", False), ("records_completed__isnull", False)),
                fields=["batch_export_on_demand", "status", "-data_interval_end"],
                name="be_run_ondemand_completed_idx",
            ),
        ),
    ]
