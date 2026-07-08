# Adds a nullable tsvector column backing full-text relevance search over
# chunks (replacing the word-level ILIKE scan). The column is additive and
# nullable — a brief lock, safe online. The vector itself is populated in
# application code (`logic._bulk_create_chunks`), not a trigger — the test
# schema is built from model state with migrations disabled, so a
# migration-only trigger would be absent there. The backing GIN index is built
# CONCURRENTLY in a separate non-atomic migration (0009).

from django.contrib.postgres.search import SearchVectorField
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("business_knowledge", "0007_knowledgedocument_classification_attempts"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledgechunk",
            name="content_search_vector",
            field=SearchVectorField(null=True),
        ),
    ]
