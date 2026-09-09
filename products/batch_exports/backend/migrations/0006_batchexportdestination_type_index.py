from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    """Index `posthog_batchexportdestination.type`, the only destination column read paths
    filter on after joining from `posthog_batchexport` (list endpoint, weekly usage report,
    billing limits). SafeAddIndexConcurrently builds it with CREATE INDEX CONCURRENTLY
    (SHARE UPDATE EXCLUSIVE, so reads and writes are not blocked), which needs atomic = False.
    """

    atomic = False

    dependencies = [
        ("batch_exports", "0005_add_batch_export_source"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="batchexportdestination",
            index=models.Index(fields=["type"], name="batch_export_dest_type_idx"),
        ),
    ]
