from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 2 of 2: Drop the is_calculating column from posthog_alertconfiguration.

    The field was removed from Django state in migration 1157. This migration
    drops the physical column. Safe to deploy once 1157 has been rolled out
    everywhere — any old code still reading the column would have failed at
    migration 1157 time.
    """

    dependencies = [("posthog", "1157_remove_alertconfiguration_is_calculating")]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE posthog_alertconfiguration DROP COLUMN IF EXISTS is_calculating;",
            reverse_sql="ALTER TABLE posthog_alertconfiguration ADD COLUMN IF NOT EXISTS is_calculating boolean DEFAULT false;",
        ),
    ]
