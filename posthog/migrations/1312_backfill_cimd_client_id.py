from django.db import migrations
from django.db.models import F


def backfill_cimd_client_id(apps, schema_editor):
    """Move each CIMD app's wire identifier (its metadata-document URL) into client_id.

    CIMD clients have always identified themselves by their metadata URL; the client_id
    column held an unused generated value while the URL lived in cimd_metadata_url.
    Uniqueness carries over: cimd_metadata_url is itself unique, and a URL can never
    collide with a generated opaque client_id.
    """
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthApplication.objects.filter(is_cimd_client=True, cimd_metadata_url__isnull=False).exclude(
        cimd_metadata_url=""
    ).update(client_id=F("cimd_metadata_url"))


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1311_alter_oauthapplication_client_id"),
    ]

    operations = [
        # Reverse is a no-op: pre-backfill code never reads a CIMD app's client_id
        # (it resolves the URL via cimd_metadata_url, which stays populated), so the
        # discarded generated values do not need restoring on rollback.
        migrations.RunPython(backfill_cimd_client_id, migrations.RunPython.noop),
    ]
