from django.db import migrations

WIZARD_CLIENT_ID = "posthog-wizard"


def create_provisioning_partners(apps, schema_editor):
    from django.conf import settings

    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    # --- Stripe ---
    stripe_client_id = getattr(settings, "STRIPE_POSTHOG_OAUTH_CLIENT_ID", "")
    stripe_secret = getattr(settings, "STRIPE_APP_SECRET_KEY", "")
    stripe_callback = getattr(settings, "STRIPE_ORCHESTRATOR_CALLBACK_URL", "")

    if stripe_client_id:
        update_fields = {
            "provisioning_auth_method": "hmac",
            "provisioning_signing_secret": stripe_secret,
            "provisioning_partner_type": "stripe",
            "provisioning_can_create_accounts": True,
            "provisioning_can_provision_resources": True,
        }
        if stripe_callback:
            update_fields["redirect_uris"] = stripe_callback
        OAuthApplication.objects.filter(
            client_id=stripe_client_id,
            provisioning_auth_method="",
        ).update(**update_fields)

    # --- Wizard ---
    if not OAuthApplication.objects.filter(client_id=WIZARD_CLIENT_ID).exists():
        from oauthlib.common import generate_token

        OAuthApplication.objects.bulk_create(
            [
                OAuthApplication(
                    client_id=WIZARD_CLIENT_ID,
                    name="PostHog Wizard",
                    client_secret=generate_token(),
                    client_type="confidential",
                    authorization_grant_type="authorization-code",
                    redirect_uris="http://localhost:8239/callback",
                    algorithm="RS256",
                    is_first_party=True,
                    provisioning_auth_method="pkce",
                    provisioning_partner_type="wizard",
                    provisioning_can_create_accounts=True,
                    provisioning_can_provision_resources=True,
                )
            ]
        )
    else:
        OAuthApplication.objects.filter(
            client_id=WIZARD_CLIENT_ID,
            provisioning_auth_method="",
        ).update(
            provisioning_auth_method="pkce",
            provisioning_partner_type="wizard",
            provisioning_can_create_accounts=True,
            provisioning_can_provision_resources=True,
            is_first_party=True,
        )


def reverse_provisioning_partners(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthApplication.objects.filter(provisioning_partner_type__in=["stripe", "wizard"]).update(
        provisioning_auth_method="",
        provisioning_signing_secret="",
        provisioning_partner_type="",
        provisioning_can_create_accounts=False,
    )
    OAuthApplication.objects.filter(client_id=WIZARD_CLIENT_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1090_oauth_provisioning_fields"),
    ]

    operations = [
        migrations.RunPython(create_provisioning_partners, reverse_provisioning_partners),
    ]
