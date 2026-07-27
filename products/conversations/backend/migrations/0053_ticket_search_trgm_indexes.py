from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import migrations
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Upper

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds can't run in a transaction.
    atomic = False

    dependencies = [("conversations", "0052_ticket_organization_id_source")]

    # Indexes are on UPPER(...) because icontains compiles to UPPER(col) LIKE UPPER(pattern)
    # on Postgres. pg_trgm is already installed (posthog migration 0034).
    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper("email_subject"), name="gin_trgm_ops"),
                name="conv_ticket_subject_trgm",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper(KeyTextTransform("name", "anonymous_traits")), name="gin_trgm_ops"),
                name="conv_ticket_anon_name_trgm",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=GinIndex(
                OpClass(Upper(KeyTextTransform("email", "anonymous_traits")), name="gin_trgm_ops"),
                name="conv_ticket_anon_email_trgm",
            ),
        ),
    ]
