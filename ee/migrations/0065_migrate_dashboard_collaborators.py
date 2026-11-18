from django.db import migrations

from posthog.rbac.migrations.rbac_dashboard_migration import rbac_dashboard_access_control_migration


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ee", "0064_split_identity_provider_config_scopes"),
    ]

    operations = [
        # Convert legacy collaborator permissions before the next migration removes
        # DashboardPrivilege and its checks. Without this, an upgrade lets previously
        # excluded members edit collaborator-restricted dashboards and enable sharing.
        migrations.RunPython(
            rbac_dashboard_access_control_migration,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
