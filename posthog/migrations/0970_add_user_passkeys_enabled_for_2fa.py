# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0969_add_oauth_is_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="passkeys_enabled_for_2fa",
            field=models.BooleanField(
                default=False,
                help_text="Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.",
            ),
        ),
    ]
