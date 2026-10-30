from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [("ee", "0067_remove_scimrequestlog_identity_provider_config_and_more")]

    operations = [
        SafeDropTable("ee_dashboardprivilege"),
    ]
