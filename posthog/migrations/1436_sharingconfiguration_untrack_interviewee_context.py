from django.db import migrations

from posthog.migration_helpers import DropForeignKey, untrack_field


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1435_delete_user_interview_sharing_configurations"),
    ]

    operations = [
        untrack_field(
            "sharingconfiguration",
            "interviewee_context",
            database_operations=[DropForeignKey("posthog_sharingconfiguration", column="interviewee_context_id")],
        ),
    ]
