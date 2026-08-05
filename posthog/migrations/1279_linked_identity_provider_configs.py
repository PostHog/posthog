import django.db.models.deletion
from django.db import migrations, models

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
    dependencies = [("posthog", "1278_identityproviderconfig_config_scope_and_more")]

    operations = [
        migrations.CreateModel(
            name="LinkedIdentityProviderConfig",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "identity_provider_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_identity_provider_configs",
                        to="posthog.identityproviderconfig",
                    ),
                ),
                (
                    "organization_domain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="linked_identity_provider_configs",
                        to="posthog.organizationdomain",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("organization_domain", "identity_provider_config"),
                        name="unique_linked_identity_provider_config",
                    )
                ],
            },
        ),
        migrations.RunPython(
            backfill_linked_identity_provider_configs,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
