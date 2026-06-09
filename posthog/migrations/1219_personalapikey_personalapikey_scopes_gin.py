import django.contrib.postgres.indexes
from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations


class Migration(migrations.Migration):
    # CONCURRENTLY so building the GIN index doesn't take an ACCESS EXCLUSIVE lock on
    # personal_api_key (a hot, core table). Concurrent index builds can't run inside a
    # transaction, so the migration must be non-atomic.
    atomic = False

    dependencies = [
        ("posthog", "1218_backfill_credential_gateway_bindings"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="personalapikey",
            index=django.contrib.postgres.indexes.GinIndex(fields=["scopes"], name="personalapikey_scopes_gin"),
        ),
    ]
