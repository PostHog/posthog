from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0002_finalize_fks"),
        ("posthog", "1023_dashboardtile_show_description"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name="team",
                    name="session_recording_encryption",
                ),
            ],
            database_operations=[],
        ),
    ]
