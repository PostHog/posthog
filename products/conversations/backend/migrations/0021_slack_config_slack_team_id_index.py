from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0020_backfill_slack_config_slack_team_id"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="teamconversationsslackconfig",
            index=models.Index(fields=["slack_team_id"], name="conv_slack_cfg_team_id_idx"),
        ),
    ]
