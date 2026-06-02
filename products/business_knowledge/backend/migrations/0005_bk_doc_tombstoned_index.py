# Index backing the cross-team tombstone hard-delete sweep. Concurrent build
# avoids locking the documents table; isolated in its own migration so a
# failed build doesn't block the rest of the schema change.

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0004_bk_doc_pending_classify_index"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="knowledgedocument",
            index=models.Index(fields=["tombstoned_at"], name="bk_doc_tombstoned"),
        ),
    ]
