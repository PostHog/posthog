from django.db import migrations


def move_google_cloud_tokens(apps, schema_editor):
    """
    Move access_token from config to sensitive_config for google-pubsub and
    google-cloud-storage integrations. Also restructure sensitive_config to
    nest existing key_info under a "key_info" key (matching the new code pattern).
    """
    Integration = apps.get_model("posthog", "Integration")

    for integration in Integration.objects.filter(kind__in=["google-pubsub", "google-cloud-storage"]):
        access_token = integration.config.pop("access_token", None)
        if access_token is not None:
            # If sensitive_config doesn't already have "key_info" wrapper,
            # the existing sensitive_config IS the key_info
            if "key_info" not in integration.sensitive_config:
                integration.sensitive_config = {
                    "key_info": integration.sensitive_config,
                    "access_token": access_token,
                }
            else:
                integration.sensitive_config["access_token"] = access_token
            integration.save(update_fields=["config", "sensitive_config"])


def move_vercel_credentials(apps, schema_editor):
    """
    Move credentials from config to sensitive_config for Vercel
    organization integrations.
    """
    OrganizationIntegration = apps.get_model("posthog", "OrganizationIntegration")

    for integration in OrganizationIntegration.objects.filter(kind="vercel"):
        credentials = integration.config.pop("credentials", None)
        if credentials is not None:
            if not integration.sensitive_config:
                integration.sensitive_config = {}
            integration.sensitive_config["credentials"] = credentials
            integration.save(update_fields=["config", "sensitive_config"])


class Migration(migrations.Migration):
    dependencies = [("posthog", "1070_add_unique_cohort_kind_per_team")]

    operations = [
        migrations.RunPython(move_google_cloud_tokens, migrations.RunPython.noop, elidable=True),
        migrations.RunPython(move_vercel_credentials, migrations.RunPython.noop, elidable=True),
    ]
