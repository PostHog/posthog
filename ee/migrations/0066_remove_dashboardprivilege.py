from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0065_migrate_dashboard_collaborators"),
    ]

    operations = [
        # The privilege table stays in Postgres so pods on the previous release keep reading it.
        # Removing the model from state stops Django cascading into it, so its foreign keys must
        # go in the same migration or a dashboard or user delete fails at COMMIT.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="DashboardPrivilege"),
            ],
            database_operations=[
                DropForeignKey("ee_dashboardprivilege", column=["dashboard_id", "user_id"]),
            ],
        ),
    ]
