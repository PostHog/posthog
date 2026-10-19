from django.db import migrations

from posthog.migration_helpers import SafeDropTable


class Migration(migrations.Migration):
    """Drop the table 1398 took out of Django state.

    1398 removed UserProductList from state and dropped its foreign keys, and kept the table so
    pods on the old release could still read it through a rolling deploy. Nothing reads it now.
    """

    dependencies = [
        ("posthog", "1400_file_system_view_days"),
    ]

    operations = [
        SafeDropTable("posthog_userproductlist"),
    ]
