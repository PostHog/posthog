from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("conversations", "0068_alter_emailchannelsetup_team_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="ticket",
            index=models.Index(fields=["team", "-created_at"], name="posthog_con_team_created_idx"),
        ),
    ]
