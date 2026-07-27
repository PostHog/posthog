# Index backing the cross-team tombstone hard-delete sweep. Concurrent build
# avoids locking the documents table; isolated in its own migration so a
# failed build doesn't block the rest of the schema change.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0004_bk_doc_pending_classify_index"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgedocument",
                    index=models.Index(fields=["tombstoned_at"], name="bk_doc_tombstoned"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_doc_tombstoned",
                    table_name="posthog_business_knowledge_knowledgedocument",
                    columns="(tombstoned_at)",
                ),
            ],
        ),
    ]
