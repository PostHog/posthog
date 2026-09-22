from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction; keep them in their own migration.
    atomic = False

    dependencies = [
        ("conversations", "0070_conversationdelivery"),
        ("posthog", "1374_teamheatmapconfig_capture_enforcement_started_at_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="emailthreadparticipant",
            index=models.Index(fields=["team", "thread", "kind"], name="email_participant_kind_idx"),
        ),
    ]
