from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0070_conversationdelivery"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper(KeyTextTransform("name", "anonymous_traits")), name="gin_trgm_ops"),
                name="posthog_con_trait_name_trgm",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper(KeyTextTransform("email", "anonymous_traits")), name="gin_trgm_ops"),
                name="posthog_con_trait_email_trgm",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper("email_subject"), name="gin_trgm_ops"),
                name="posthog_con_subject_trgm",
            ),
        ),
    ]
