from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("posthog", "1300_identityproviderconfig_saml_relay_state_unique")]

    operations = [
        migrations.AddField(
            model_name="oauthapplication",
            name="allow_redirect_uri_wildcards",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text="Allow wildcard hostname redirect URIs for this first-party application only.",
            ),
        ),
    ]
