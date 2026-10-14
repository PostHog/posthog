from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("business_knowledge", "0022_playground_chat_sandbox_task"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="knowledgedocument",
            index=models.Index(
                condition=models.Q(("safety_verdict", "unknown"), ("tombstoned_at__isnull", True)),
                fields=["classification_attempts", "id"],
                name="bk_doc_classify_queue",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="knowledgedocument",
            index=models.Index(
                condition=models.Q(
                    ("embeddings_emitted_at__isnull", True),
                    ("safety_verdict", "safe"),
                    ("tombstoned_at__isnull", True),
                ),
                fields=["id"],
                name="bk_doc_embed_pending",
            ),
        ),
    ]
