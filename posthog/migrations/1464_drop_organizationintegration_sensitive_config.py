from django.db import migrations


class Migration(migrations.Migration):
    """Drop the column that held saved Vercel tokens, which 1463 stopped tracking.

    The drop waits for its own release. While the release before 1463 is still up, its pods name
    this column in every SELECT on the table, so dropping it early errors on an undefined column
    across Vercel flag sync, installation and billing. posthog_organizationintegration is small and
    not one of the hot tables, so the ACCESS EXCLUSIVE lock is short.

    IF EXISTS keeps this idempotent under bin/migrate retries.
    """

    dependencies = [("posthog", "1463_organizationintegration_untrack_sensitive_config")]

    operations = [
        migrations.RunSQL(
            sql='ALTER TABLE "posthog_organizationintegration" DROP COLUMN IF EXISTS "sensitive_config"',
            # The saved tokens are gone either way, and nothing reads the column since 1463.
            reverse_sql='ALTER TABLE "posthog_organizationintegration" ADD COLUMN IF NOT EXISTS "sensitive_config" jsonb NULL',
        ),
    ]
