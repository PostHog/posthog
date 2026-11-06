from django.db import migrations


class Migration(migrations.Migration):
    # This migration has no operations. The first version dropped the legacy tagged item
    # constraints and foreign keys in one transaction, and that transaction deadlocked in prod-eu.
    # Dev already applied the first version, so the file stays. A later migration re-lands the change.
    dependencies = [
        ("posthog", "1375_file_system_home_folder"),
    ]

    operations = []
