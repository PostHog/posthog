from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    dependencies = [
        ("data_modeling", "0047_remove_datawarehousemodelpath_state"),
    ]

    operations = [
        SafeDropTable("posthog_datawarehousemodelpath"),
    ]
