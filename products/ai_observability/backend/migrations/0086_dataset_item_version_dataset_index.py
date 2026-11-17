from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("ai_observability", "0085_tagger_migrated_to_evaluation")]

    operations = [
        SafeAddIndexConcurrently(
            model_name="datasetitemversion",
            index=models.Index(fields=["dataset", "team", "id"], name="llma_item_ver_v2_dataset_idx"),
        ),
    ]
