import django.db.models.deletion
from django.db import migrations, models

import posthog.models.utils


def backfill_domain_mappings(apps, schema_editor):
    OrganizationDomain = apps.get_model("posthog", "OrganizationDomain")
    IdentityProviderConfigDomain = apps.get_model("posthog", "IdentityProviderConfigDomain")

    mappings = []
    for domain in OrganizationDomain.objects.exclude(identity_provider_config_id__isnull=True).iterator():
        for kind in ("saml", "scim", "id_jag"):
            mappings.append(
                IdentityProviderConfigDomain(
                    organization_id=domain.organization_id,
                    identity_provider_config_id=domain.identity_provider_config_id,
                    organization_domain_id=domain.id,
                    kind=kind,
                )
            )
        if len(mappings) >= 999:
            IdentityProviderConfigDomain.objects.bulk_create(mappings, batch_size=999, ignore_conflicts=True)
            mappings.clear()
    if mappings:
        IdentityProviderConfigDomain.objects.bulk_create(mappings, batch_size=999, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1255_wizard_runs_rate_limit_and_provisioned_onboarding_reason"),
    ]

    operations = [
        migrations.CreateModel(
            name="IdentityProviderConfigDomain",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "kind",
                    models.CharField(choices=[("saml", "SAML"), ("scim", "SCIM"), ("id_jag", "XAA")], max_length=16),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "identity_provider_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="domain_mappings",
                        to="posthog.identityproviderconfig",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identity_provider_config_domain_mappings",
                        to="posthog.organization",
                    ),
                ),
                (
                    "organization_domain",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="identity_provider_config_mappings",
                        to="posthog.organizationdomain",
                    ),
                ),
            ],
            options={
                "verbose_name": "identity provider config domain mapping",
            },
        ),
        migrations.AddConstraint(
            model_name="identityproviderconfigdomain",
            constraint=models.UniqueConstraint(
                fields=("organization_domain", "kind"), name="unique_idp_config_kind_per_organization_domain"
            ),
        ),
        migrations.RunPython(backfill_domain_mappings, migrations.RunPython.noop),
    ]
