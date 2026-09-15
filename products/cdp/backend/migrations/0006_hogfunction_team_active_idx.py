from django.db import migrations, models
from django.db.models import Q

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY can't run inside a transaction.
    atomic = False

    dependencies = [
        ("cdp", "0005_repair_hogfunction_batch_export_id_index"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="hogfunction",
            index=models.Index(
                fields=["team"],
                condition=Q(deleted=False),
                name="hog_func_team_active_idx",
            ),
        ),
    ]
