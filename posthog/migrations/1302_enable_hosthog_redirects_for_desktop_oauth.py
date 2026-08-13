from django.db import migrations

DESKTOP_OAUTH_CLIENT_IDS = (
    "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W",
    "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9",
    "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ",
)
HOSTHOG_CALLBACK = "https://*.hosthog.dev/callback"


def enable_hosthog_redirects(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    for application in OAuthApplication.objects.filter(
        client_id__in=DESKTOP_OAUTH_CLIENT_IDS,
        is_first_party=True,
    ):
        redirect_uris = application.redirect_uris.split()
        if HOSTHOG_CALLBACK not in redirect_uris:
            application.redirect_uris = " ".join([*redirect_uris, HOSTHOG_CALLBACK])
        application.allow_redirect_uri_wildcards = True
        application.save(update_fields=["redirect_uris", "allow_redirect_uri_wildcards"])


class Migration(migrations.Migration):
    dependencies = [("posthog", "1301_oauthapplication_allow_redirect_uri_wildcards")]

    operations = [migrations.RunPython(enable_hosthog_redirects, migrations.RunPython.noop)]
