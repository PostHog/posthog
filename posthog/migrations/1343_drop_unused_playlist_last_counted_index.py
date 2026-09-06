from django.db import migrations

from posthog.migration_helpers import SafeRemoveIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1342_drop_cimd_blocklist_table"),
    ]

    operations = [
        SafeRemoveIndexConcurrently(
            model_name="sessionrecordingplaylist",
            name="deleted_n_last_count_idx",
        ),
    ]
