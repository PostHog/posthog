from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently, SafeAddIndexConcurrently, SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1351_drop_persistedfolder_table"),
    ]

    # The partial index is built before the full one it replaces is dropped, so campaign_key
    # lookups never run without an index to use.
    operations = [
        SafeAddIndexConcurrently(
            model_name="messagingrecord",
            index=models.Index(
                condition=models.Q(("sent_at__isnull", False)),
                fields=["campaign_key"],
                name="messagingrecord_campaign_sent",
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="messagingrecord",
            index=models.Index(fields=["created_at"], name="messagingrecord_created_idx"),
        ),
        SafeRemoveIndexConcurrently(
            model_name="messagingrecord",
            name="messagingrecord_campaign_idx",
        ),
        # Redundant since it was added in 0352: `unique_together` on (email_hash, campaign_key)
        # is the stricter constraint, so this index can never reject a row the constraint
        # accepts, and it serves no lookup the constraint's own index does not. It is raw SQL
        # from 0352, so Django holds no state for it.
        DropIndexConcurrently(
            index_name="idx_messagingrecord_unique_on_email_hash_campaign_key_campaign_count",
            table_name="posthog_messagingrecord",
            columns="(email_hash, campaign_key, campaign_count)",
            unique=True,
        ),
    ]
