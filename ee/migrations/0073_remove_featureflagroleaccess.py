from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0072_validate_role_organization_access_level"),
    ]

    operations = [
        # The table stays in Postgres so pods on the previous release keep reading it.
        # Removing the model from state stops Django cascading into it, so its foreign keys must
        # go in the same migration or a feature flag or role delete fails at COMMIT.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="FeatureFlagRoleAccess"),
            ],
            database_operations=[
                DropForeignKey("ee_featureflagroleaccess", column=["feature_flag_id", "role_id"]),
            ],
        ),
    ]
