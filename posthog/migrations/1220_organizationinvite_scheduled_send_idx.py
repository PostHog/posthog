from django.db import migrations, models

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1219_organizationinvite_postpone_fields"),
    ]

    operations = [
        # Partial index over only the invites with a pending postpone (scheduled_send_at not null),
        # so the send_scheduled_invites periodic task scans a tiny slice rather than the whole table.
        # The bare Django AddIndexConcurrently op is non-idempotent and blocked by CI; the helper
        # disables lock_timeout, recovers from invalid leftovers, and emits IF NOT EXISTS.
        # SeparateDatabaseAndState keeps Django's index state in sync with the model Meta.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="organizationinvite",
                    index=models.Index(
                        fields=["scheduled_send_at"],
                        name="posthog_inv_sched_send_idx",
                        condition=models.Q(scheduled_send_at__isnull=False),
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_inv_sched_send_idx",
                    table_name="posthog_organizationinvite",
                    columns="(scheduled_send_at)",
                    where="WHERE scheduled_send_at IS NOT NULL",
                ),
            ],
        ),
    ]
