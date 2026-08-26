from django.db import migrations

CHUNK_SIZE = 200


def backfill_linked_identity_provider_configs(apps, schema_editor):
    OrganizationDomain = apps.get_model("posthog", "OrganizationDomain")
    LinkedIdentityProviderConfig = apps.get_model("posthog", "LinkedIdentityProviderConfig")

    links = (
        OrganizationDomain.objects.filter(identity_provider_config__isnull=False)
        .values_list("id", "identity_provider_config_id")
        .iterator(chunk_size=CHUNK_SIZE)
    )

    chunk = []
    for domain_id, config_id in links:
        chunk.append(
            LinkedIdentityProviderConfig(
                organization_domain_id=domain_id,
                identity_provider_config_id=config_id,
            )
        )
        if len(chunk) == CHUNK_SIZE:
            LinkedIdentityProviderConfig.objects.bulk_create(
                chunk,
                ignore_conflicts=True,
                batch_size=CHUNK_SIZE,
            )
            chunk = []

    if chunk:
        LinkedIdentityProviderConfig.objects.bulk_create(
            chunk,
            ignore_conflicts=True,
            batch_size=CHUNK_SIZE,
        )


class Migration(migrations.Migration):
    dependencies = [("posthog", "1287_linked_identity_provider_configs")]

    operations = [
        migrations.RunPython(
            backfill_linked_identity_provider_configs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
