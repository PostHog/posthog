from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1024_remove_team_session_recording_encryption"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE posthog_team DROP COLUMN IF EXISTS session_recording_encryption",
                    reverse_sql="ALTER TABLE posthog_team ADD COLUMN session_recording_encryption boolean NULL DEFAULT false",
                ),
            ],
        ),
    ]
