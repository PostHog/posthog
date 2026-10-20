from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [
        ("ee", "0066_remove_dashboardprivilege"),
    ]

    operations = [
        SafeDropTable("ee_dashboardprivilege"),
    ]
