from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 2 of 2: Drop the is_calculating column from posthog_alertconfiguration.

    The field was removed from Django state in the phase-1
    ``remove_alertconfiguration_is_calculating`` migration. This migration drops
    the physical column. Safe to deploy once that migration has rolled out
    everywhere — any old code still reading the column would have failed by then.
    """

    dependencies = [("posthog", "1174_taggeditem_account_unique_constraint")]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE posthog_alertconfiguration DROP COLUMN IF EXISTS is_calculating;",
            reverse_sql="ALTER TABLE posthog_alertconfiguration ADD COLUMN IF NOT EXISTS is_calculating boolean DEFAULT false;",
        ),
    ]
