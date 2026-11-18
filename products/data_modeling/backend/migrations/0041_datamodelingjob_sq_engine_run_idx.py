from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("data_modeling", "0040_add_managed_warehouse_job_engine"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(fields=["saved_query", "engine", "-last_run_at"], name="datamodelingjob_sq_engine_run"),
        ),
    ]
