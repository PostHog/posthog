# Partial index backing the cross-team "docs awaiting classification" scan.
# Partial on the only value ever queried (`unknown`) so it stays ~0 rows once
# docs are classified. Concurrent build avoids locking the documents table.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0003_knowledgedocument_safety_reason_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgedocument",
                    index=models.Index(
                        fields=["tombstoned_at"],
                        name="bk_doc_pending_classify",
                        condition=models.Q(safety_verdict="unknown"),
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_doc_pending_classify",
                    table_name="posthog_business_knowledge_knowledgedocument",
                    columns="(tombstoned_at)",
                    where="WHERE safety_verdict = 'unknown'",
                ),
            ],
        ),
    ]
