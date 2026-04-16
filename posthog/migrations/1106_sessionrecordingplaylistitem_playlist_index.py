from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1105_alter_oauthapplication_authorization_grant_type"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="sessionrecordingplaylistitem",
            index=models.Index(fields=["playlist"], name="srpi_playlist_idx"),
        ),
    ]
