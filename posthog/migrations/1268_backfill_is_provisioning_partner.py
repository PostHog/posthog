from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

# Methods whose apps become provisioning partners under the new boolean. Chosen to preserve
# today's behavior exactly: these are the two values the resource endpoints currently accept
# outstanding access tokens for. "hmac" is excluded because those apps already fail closed
# everywhere, and "" was never a partner.
PARTNER_AUTH_METHODS = ["pkce", "bearer"]


def backfill_is_provisioning_partner(apps, schema_editor):
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    partners = OAuthApplication.objects.filter(provisioning_auth_method__in=PARTNER_AUTH_METHODS)
    partners.update(is_provisioning_partner=True)

    # A "bearer" partner proved itself with an OAuth access token, so nothing ever required
    # its application to carry a usable client_secret. Afterwards a confidential app is
    # expected to authenticate as an OAuth client, and one with a blank secret resolves to
    # client_secret_post with nothing to verify against, so it can no longer reach any
    # provisioning endpoint. 1266 only just added jwks_uri, so every row still has it null and
    # none can be on private_key_jwt instead. Log the affected ids rather than let them fail
    # silently after deploy; each needs a secret set or a jwks_uri published before those
    # columns are dropped for real in a later release.
    stranded = list(partners.filter(client_type="confidential", client_secret="").values_list("id", flat=True))
    if stranded:
        logger.warning("provisioning_partners_without_client_credentials", application_ids=stranded)


class Migration(migrations.Migration):
    """Backfill is_provisioning_partner from provisioning_auth_method.

    Alone in its own migration: a RunPython sharing a file with schema changes holds locks for
    the whole file. It has to run while provisioning_auth_method is still in the model state,
    which is why it sits before 1269 rather than after.
    """

    dependencies = [("posthog", "1267_oauth_client_authentication")]

    operations = [
        migrations.RunPython(backfill_is_provisioning_partner, migrations.RunPython.noop, elidable=True),
    ]
