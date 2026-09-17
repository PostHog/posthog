from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1368_sessionrecording_untrack_lts_fields"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="team",
            index=models.Index(
                fields=["id"],
                include=(
                    "organization_id",
                    "api_token",
                    "capture_console_log_opt_in",
                    "session_recording_retention_period",
                ),
                condition=models.Q(("session_recording_opt_in", True)),
                name="posthog_team_replay_optin_idx",
            ),
        ),
    ]
