from datetime import timedelta

from django.db import migrations
from django.utils import timezone

# A config and its domain link are created in two separate requests, so a valid but not-yet-linked
# config can exist while this migration runs. Only sweep configs old enough that no in-flight request
# could still be about to link them.
UNLINKED_GRACE_PERIOD = timedelta(days=1)


def delete_orphaned_identity_provider_configs(apps, schema_editor):
    IdentityProviderConfig = apps.get_model("posthog", "IdentityProviderConfig")
    IdentityProviderConfig.objects.filter(
        domains__isnull=True, created_at__lt=timezone.now() - UNLINKED_GRACE_PERIOD
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1285_drop_desktop_file_system"),
    ]

    operations = [
        migrations.RunPython(
            delete_orphaned_identity_provider_configs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
