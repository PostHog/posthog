from django.conf import settings
from django.db import migrations
from django.db.models import Q


def backfill_can_issue_deep_links(apps, schema_editor):
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
