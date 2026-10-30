from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0024_knowledge_libraries"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="knowledgechunk",
            name="bk_chunk_content_trgm",
        ),
    ]
