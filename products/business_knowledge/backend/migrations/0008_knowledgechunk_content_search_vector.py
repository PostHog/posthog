# Adds a tsvector column + GIN index backing full-text relevance search over
# chunks (replacing the word-level ILIKE scan). The column is nullable and
# additive (safe online); the GIN index is built CONCURRENTLY in its own
# non-atomic migration so it never holds a write lock. The vector itself is
# populated in application code (`logic._bulk_create_chunks`), not a trigger —
# the test schema is built from model state with migrations disabled, so a
# migration-only trigger would be absent there.

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0007_knowledgedocument_classification_attempts"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgechunk",
            name="content_search_vector",
            field=SearchVectorField(null=True),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="knowledgechunk",
                    index=GinIndex(
                        fields=["content_search_vector"],
                        name="bk_chunk_content_tsv",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="bk_chunk_content_tsv",
                    table_name="posthog_business_knowledge_knowledgechunk",
                    columns="(content_search_vector)",
                    using="gin",
                ),
            ],
        ),
    ]
