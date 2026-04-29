from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1060_alter_integration_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="session_recording_trigger_groups",
            field=models.JSONField(
                null=True,
                blank=True,
                help_text="V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.",
            ),
        ),
    ]
