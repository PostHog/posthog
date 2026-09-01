from django.db import migrations

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    """
    Rebuild the `created_by_id` index on posthog_resourcetransfer.

    Migration 1008 built it with a raw `CREATE INDEX CONCURRENTLY IF NOT EXISTS`. A cancelled
    build left the index invalid (indisvalid = false) in EU production. `IF NOT EXISTS` never
    checks indisvalid, so the guard skips the invalid leftover and nothing rebuilds it.

    `CreateIndexConcurrently` drops an invalid leftover first, then recreates the index, so this
    migration repairs the index and stays idempotent under bin/migrate retries.

    Database-only: `created_by` is a plain ForeignKey, so Django state already declares the index.
    """

    atomic = False  # Required for CREATE INDEX CONCURRENTLY

    dependencies = [
        ("posthog", "1331_messagingrecord_campaign_key_idx"),
    ]

    operations = [
        CreateIndexConcurrently(
            index_name="posthog_resourcetransfer_created_by_id_cfdd93a0",
            table_name="posthog_resourcetransfer",
            columns="(created_by_id)",
        ),
    ]
