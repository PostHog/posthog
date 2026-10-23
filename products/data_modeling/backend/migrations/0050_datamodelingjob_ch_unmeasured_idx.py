from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [("data_modeling", "0049_datamodelingjob_bytes_read")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datamodelingjob",
            index=models.Index(
                condition=models.Q(("bytes_read__isnull", True), ("engine", "clickhouse")),
                fields=["workflow_run_id"],
                name="datamodelingjob_ch_unmeasured",
            ),
        ),
    ]
