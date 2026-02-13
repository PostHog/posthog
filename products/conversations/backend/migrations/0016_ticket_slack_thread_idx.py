from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0015_ticket_slack_fields"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="ticket",
            index=models.Index(
                fields=["team", "slack_channel_id", "slack_thread_ts"],
                name="posthog_con_slack_thread_idx",
            ),
        ),
    ]
