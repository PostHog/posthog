from datetime import UTC, datetime

from django.db import migrations
from django.db.models import F

from posthog.migration_helpers import untrack_field

BATCH_SIZE = 1_000


def copy_bytes_read(apps, schema_editor):
    DataModelingJob = apps.get_model("data_modeling", "DataModelingJob")
    # Only managed warehouse runs wrote bytes_read, and only after it shipped in October 2026.
    # Those runs set last_run_at in the same save, so the bound uses dmjob_usage_run
    # instead of scanning the whole table.
    pending = DataModelingJob.objects.filter(
        last_run_at__gte=datetime(2026, 10, 1, tzinfo=UTC),
        bytes_read__isnull=False,
        read_bytes__isnull=True,
    )
    ids = list(pending.values_list("id", flat=True))
    for start in range(0, len(ids), BATCH_SIZE):
        DataModelingJob.objects.filter(id__in=ids[start : start + BATCH_SIZE]).update(
            read_bytes=F("bytes_read"),
            usage_updated_at=F("last_run_at"),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0055_backfill_datawarehousesavedquery_query_updated_at"),
    ]

    operations = [
        migrations.RunPython(copy_bytes_read, migrations.RunPython.noop),
        untrack_field("datamodelingjob", "bytes_read"),
    ]
