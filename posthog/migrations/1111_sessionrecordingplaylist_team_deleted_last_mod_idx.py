from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1110_sessionrecordingplaylistitem_playlist_index"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="sessionrecordingplaylist",
            index=models.Index(
                fields=["team", "deleted", "-last_modified_at"],
                name="srp_team_deleted_last_mod_idx",
            ),
        ),
    ]
