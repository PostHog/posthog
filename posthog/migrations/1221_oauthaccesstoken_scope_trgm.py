from django.contrib.postgres.indexes import GinIndex
from django.db import migrations
from django.db.models import Q

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the trigram GIN index doesn't take an ACCESS EXCLUSIVE lock
    # on oauthaccesstoken. Concurrent builds can't run in a transaction, so the migration
    # is non-atomic. CreateIndexConcurrently (vs Django's AddIndexConcurrently) disables
    # lock_timeout/statement_timeout, drops any invalid leftover from an interrupted build,
    # and uses IF NOT EXISTS — so a transient cancellation during deploy doesn't wedge
    # retries. SeparateDatabaseAndState keeps the Django model state in sync via the
    # matching AddIndex. pg_trgm is already installed (migration 0034), so the gin_trgm_ops
    # index needs no extension op.
    atomic = False

    dependencies = [
        ("posthog", "1220_projectsecretapikey_scopes_gin"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="oauthaccesstoken",
                    index=GinIndex(
                        fields=["scope"],
                        name="oauthaccesstoken_scope_trgm",
                        opclasses=["gin_trgm_ops"],
                        condition=Q(application__isnull=False),
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="oauthaccesstoken_scope_trgm",
                    table_name="posthog_oauthaccesstoken",
                    columns="(scope gin_trgm_ops)",
                    using="gin",
                    where="WHERE application_id IS NOT NULL",
                ),
            ],
        ),
    ]
