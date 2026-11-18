from django.db import migrations


class Migration(migrations.Migration):
    """Drop the `is_hipaa` column from posthog_organization.

    Migration 1346 already removed it from Django's model state, so nothing reads or
    writes it any more. This is the second phase from safe-django-migrations.md
    "Dropping Columns": deploy the state removal, wait a full deploy cycle, then drop.

    posthog_organization is a hot table, so this needs an acknowledgment in
    hot_table_acknowledged_migrations.txt and a low-traffic deploy window. The drop
    itself is metadata-only, so the ACCESS EXCLUSIVE lock is held for microseconds
    once Postgres grants it. The risk is the wait for the lock, not the work.

    Irreversible: the column data is gone. `reverse_sql` re-adds an empty nullable
    column so the migration can be unapplied, but it cannot bring the values back.
    """

    dependencies = [
        ("posthog", "1347_drop_activitylog_detail_jsonb_ops_gin"),
    ]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "posthog_organization" DROP COLUMN IF EXISTS "is_hipaa";',
            reverse_sql='ALTER TABLE "posthog_organization" ADD COLUMN IF NOT EXISTS "is_hipaa" boolean NULL;',
        ),
    ]
