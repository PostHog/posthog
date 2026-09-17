from django.db import migrations

from posthog.migration_helpers.untrack_field import untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1366_project_deletion_scheduled_at"),
    ]

    operations = [
        untrack_field("sessionrecording", "object_storage_path", "full_recording_v2_path", "storage_version"),
    ]
