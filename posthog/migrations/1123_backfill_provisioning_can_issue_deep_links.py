from django.conf import settings
from django.db import migrations
from django.db.models import Q


def backfill_can_issue_deep_links(apps, schema_editor):
    # Trusted partners (HMAC/bearer) are admin-onboarded and need to keep issuing deep links.
    # The legacy Stripe app may exist without provisioning_auth_method set, so we also match
    # by client_id when STRIPE_POSTHOG_OAUTH_CLIENT_ID is configured. Environments without
    # that setting (CI, fresh staging) safely skip the second selector — fresh legacy Stripe
    # rows created post-deploy get the flag set in _get_legacy_stripe_oauth_app().
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    selector = Q(provisioning_auth_method__in=["hmac", "bearer"])
    legacy_stripe_client_id = getattr(settings, "STRIPE_POSTHOG_OAUTH_CLIENT_ID", "")
    if legacy_stripe_client_id:
        selector |= Q(client_id=legacy_stripe_client_id)
    OAuthApplication.objects.filter(selector).update(provisioning_can_issue_deep_links=True)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1122_oauthapplication_provisioning_can_issue_deep_links"),
    ]

    operations = [
        migrations.RunPython(backfill_can_issue_deep_links, migrations.RunPython.noop),
    ]
