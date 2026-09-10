from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # CONCURRENTLY so building the B-tree on oauthaccesstoken doesn't take an ACCESS
    # EXCLUSIVE lock on the table. Concurrent builds can't run in a transaction, so the
    # migration is non-atomic. SafeAddIndexConcurrently (vs Django's AddIndexConcurrently)
    # disables lock_timeout/statement_timeout, skips an already-valid index, and rebuilds
    # an invalid leftover from an interrupted build — so a transient cancellation during
    # deploy doesn't wedge bin/migrate retries. It tracks Django model state itself, so no
    # SeparateDatabaseAndState wrapper is needed.
    atomic = False

    dependencies = [
        ("posthog", "1246_alter_organizationdomain_id_jag_allowed_clients_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="oauthaccesstoken",
            index=models.Index(fields=["token"], name="oauthaccesstoken_token_idx"),
        ),
    ]
