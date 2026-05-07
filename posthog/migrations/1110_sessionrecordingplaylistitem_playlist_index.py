from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1109_alert_investigation_notification_gating"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="sessionrecordingplaylistitem",
            index=models.Index(fields=["playlist"], name="srpi_playlist_idx"),
        ),
    ]
