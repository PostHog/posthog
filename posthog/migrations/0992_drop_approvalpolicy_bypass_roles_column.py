from django.db import migrations


class Migration(migrations.Migration):
    """
    Phase 2 of 2: Drop the bypass_roles column from the database.

    The field was removed from Django state in migration 0991.
    Feature was never deployed, so this is safe.
    """

    dependencies = [
        ("posthog", "0991_remove_approvalpolicy_bypass_roles"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE posthog_approvalpolicy DROP COLUMN IF EXISTS bypass_roles;",
            reverse_sql="ALTER TABLE posthog_approvalpolicy ADD COLUMN IF NOT EXISTS bypass_roles jsonb DEFAULT '[]'::jsonb;",
        ),
    ]
