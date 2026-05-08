from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0034_teams_integration"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["team", "teams_channel_id", "teams_conversation_id"],
                name="posthog_con_teams_thread_idx",
            ),
        ),
    ]
