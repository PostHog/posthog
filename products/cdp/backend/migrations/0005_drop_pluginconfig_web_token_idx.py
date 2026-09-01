from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("cdp", "0004_backfill_internal_event_filter_sources"),
    ]

    operations = [
        # No query can use this index. The only reader that filters on `web_token`
        # also filters on the primary key, so Postgres resolves the row through the
        # pkey index. All other readers select the column without filtering on it.
        SafeRemoveIndexConcurrently(
            model_name="pluginconfig",
            name="posthog_plu_web_tok_ac760a_idx",
        ),
    ]
