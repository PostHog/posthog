from datetime import timedelta

from django.db import migrations
from django.utils import timezone

# A config and its domain link are created in two separate requests, so a valid but not-yet-linked
# config can exist while this migration runs. Only sweep configs old enough that no in-flight request
# could still be about to link them.
UNLINKED_GRACE_PERIOD = timedelta(days=1)


def delete_orphaned_identity_provider_configs(apps, schema_editor):
    IdentityProviderConfig = apps.get_model("posthog", "IdentityProviderConfig")
    OrganizationDomain = apps.get_model("posthog", "OrganizationDomain")
    if "_identity_provider_config" in {field.name for field in OrganizationDomain._meta.fields}:
        linked_config_ids = OrganizationDomain.objects.exclude(_identity_provider_config__isnull=True).values_list(
            "_identity_provider_config_id", flat=True
        )
    else:
        linked_config_ids = OrganizationDomain.objects.exclude(identity_provider_config__isnull=True).values_list(
            "identity_provider_config_id", flat=True
        )
    IdentityProviderConfig.objects.exclude(id__in=linked_config_ids).filter(
        created_at__lt=timezone.now() - UNLINKED_GRACE_PERIOD
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
