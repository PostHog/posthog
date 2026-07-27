# Builds the GIN index over `content_search_vector` CONCURRENTLY so it never
# holds a write lock. Isolated in its own non-atomic migration (split from the
# AddField in 0008) per the CONCURRENTLY-must-run-outside-a-transaction rule.

from django.contrib.postgres.indexes import GinIndex
from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0008_knowledgechunk_content_search_vector"),
    ]

    operations = [
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
