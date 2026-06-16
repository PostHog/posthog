from django.contrib.postgres.indexes import GinIndex
from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the GIN index doesn't take an ACCESS EXCLUSIVE lock on
    # project_secret_api_key. Concurrent builds can't run in a transaction, so the
    # migration is non-atomic. CreateIndexConcurrently (vs Django's AddIndexConcurrently)
    # disables lock_timeout/statement_timeout, drops any invalid leftover from an
    # interrupted build, and uses IF NOT EXISTS — so a transient cancellation during
    # deploy doesn't wedge retries. SeparateDatabaseAndState keeps the Django model
    # state in sync via the matching AddIndex.
    atomic = False

    dependencies = [
        ("posthog", "1219_filesystemfoldercontextgeneration"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="projectsecretapikey",
                    index=GinIndex(fields=["scopes"], name="projectsecretapikey_scopes_gin"),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="projectsecretapikey_scopes_gin",
                    table_name="posthog_projectsecretapikey",
                    columns="(scopes)",
                    using="gin",
                ),
            ],
        ),
    ]
