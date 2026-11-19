from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("ai_observability", "0071_dataset_retention")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="dataset",
            index=models.Index(fields=["last_used_at", "id"], name="llma_dataset_retention_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="dataset",
            index=models.Index(fields=["retention_checked_at", "id"], name="llma_dataset_retention_chk_idx"),
        ),
        SafeAddIndexConcurrently(
            model_name="datasetrevision",
            index=models.Index(fields=["last_used_at", "id"], name="llma_revision_retention_idx"),
        ),
    ]
