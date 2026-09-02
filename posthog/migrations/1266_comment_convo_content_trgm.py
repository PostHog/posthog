from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations, models
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("posthog", "1265_delete_duckgresserverteam")]

    # On UPPER(content) because icontains compiles to UPPER(col) LIKE UPPER(pattern) on
    # Postgres. Partial on the conversations scope: posthog_comment is shared across
    # products and the ticket search always filters on it. pg_trgm is already installed
    # (migration 0034).
    operations = [
        SafeAddIndexConcurrently(
            model_name="comment",
            index=GinIndex(
                OpClass(Upper("content"), name="gin_trgm_ops"),
                name="comment_convo_content_trgm",
                condition=models.Q(scope="conversations_ticket"),
            ),
        ),
    ]
