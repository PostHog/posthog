from django.db import migrations

from posthog.migration_helpers import untrack_field


class Migration(migrations.Migration):
    dependencies = [("posthog", "1462_alter_team_primary_dashboard")]

    operations = [
        # Phase 1 of retiring the column that held saved Vercel tokens. The column stops being NOT NULL,
        # because Django leaves it out of every INSERT once the field leaves model state, and pods on
        # the previous release still write it. The DROP COLUMN follows one deploy cycle later.
        untrack_field(
            "organizationintegration",
            "sensitive_config",
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE posthog_organizationintegration ALTER COLUMN sensitive_config DROP NOT NULL",
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
        ),
    ]
