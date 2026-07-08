# Partial index backing the cross-team embedding passes. Partial on `safe` (the
# only verdict ever embedded) so it tracks just the embeddable working set, and
# serves both the pending scan (`embeddings_emitted_at IS NULL`) and the
# reconciliation scan (`embeddings_emitted_at < cutoff`). Concurrent build
# avoids locking the documents table.

from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0010_knowledgedocument_embeddings_emitted_at"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgedocument",
                    index=models.Index(
                        fields=["embeddings_emitted_at"],
                        name="bk_doc_embed_state",
                        condition=models.Q(safety_verdict="safe"),
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_doc_embed_state",
                    table_name="posthog_business_knowledge_knowledgedocument",
                    columns="(embeddings_emitted_at)",
                    where="WHERE safety_verdict = 'safe'",
                ),
            ],
        ),
    ]
