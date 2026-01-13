# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0970_add_session_recording_encryption"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="passkeys_enabled_for_2fa",
            field=models.BooleanField(
                default=False,
                null=True,
                blank=True,
                help_text="Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.",
            ),
        ),
    ]
