# Replace the full `safety_verdict` btree with a partial index on the only
# value ever queried (`unknown`), so it shrinks to ~0 rows once docs are
# classified. Concurrent build/drop avoids locking the documents table.

from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0003_knowledgedocument_safety_reason_and_more"),
    ]

    operations = [
        RemoveIndexConcurrently(
            model_name="knowledgedocument",
            name="bk_doc_safety_verdict",
        ),
        AddIndexConcurrently(
            model_name="knowledgedocument",
            index=models.Index(
                fields=["tombstoned_at"],
                name="bk_doc_pending_classify",
                condition=models.Q(safety_verdict="unknown"),
            ),
        ),
    ]
