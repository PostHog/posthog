from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [("ee", "0073_remove_featureflagroleaccess")]

    operations = [
        SafeDropTable("ee_featureflagroleaccess"),
    ]
