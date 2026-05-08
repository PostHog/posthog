from django.db import migrations


class Migration(migrations.Migration):
    # Companion to 1153, which removed `property_type` from Django model state. New code
    # no longer sends `property_type` in INSERTs into `posthog_materializedcolumnslot`,
    # but the underlying DB column was created with NOT NULL. Drop the constraint so
    # those INSERTs succeed.
    #
    # Lives in its own migration per POSTHOG_POLICIES — RunSQL DDL and Django schema
    # operations should not share a migration.
    #
    # The column itself remains so old code (still running between deploy phases) can
    # continue writing to it. A future migration can DROP the column entirely once a
    # full deployment cycle has elapsed (the analyzer recognises the prior 1153
    # SeparateDatabaseAndState as a properly-staged state removal at that point).

    dependencies = [("posthog", "1153_materializedcolumnslot_pending_and_expand_index")]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "posthog_materializedcolumnslot" ALTER COLUMN "property_type" DROP NOT NULL',
            reverse_sql='ALTER TABLE "posthog_materializedcolumnslot" ALTER COLUMN "property_type" SET NOT NULL',
        ),
    ]
