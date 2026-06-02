# Index backing the cross-team due-source scan in the refresh coordinator.
# Concurrent build avoids locking the sources table; isolated in its own
# migration so a failed build doesn't block the rest of the schema change.

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0005_bk_doc_tombstoned_index"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="knowledgesource",
            index=models.Index(fields=["refresh_interval", "last_refresh_at"], name="bk_source_refresh_due"),
        ),
    ]
