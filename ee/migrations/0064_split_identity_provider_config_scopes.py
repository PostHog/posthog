from django.db import migrations, transaction

CHUNK_SIZE = 200


def split_identity_provider_config_scopes(apps, schema_editor):
    IdentityProviderConfig = apps.get_model("posthog", "IdentityProviderConfig")
    LinkedIdentityProviderConfig = apps.get_model("posthog", "LinkedIdentityProviderConfig")
    SCIMProvisionedUser = apps.get_model("ee", "SCIMProvisionedUser")
    SCIMRequestLog = apps.get_model("ee", "SCIMRequestLog")
    db_alias = schema_editor.connection.alias

    configs = IdentityProviderConfig.objects.using(db_alias).filter(config_scope__isnull=True)
    for config in configs.iterator(chunk_size=CHUNK_SIZE):
        with transaction.atomic(using=db_alias):
            IdentityProviderConfig.objects.using(db_alias).filter(pk=config.pk).update(
                saml_relay_state=None,
                scim_slug=None,
            )
            shared = {
                "organization_id": config.organization_id,
                "name": config.name,
                "domain_scope": config.domain_scope,
            }
            scopes = (
                (
                    "saml",
                    ("saml_entity_id", "saml_acs_url", "saml_x509_cert"),
                    ("saml_entity_id", "saml_acs_url", "saml_x509_cert", "saml_relay_state"),
                ),
                (
                    "oidc",
                    ("oidc_issuer_url", "oidc_client_id", "oidc_credentials"),
                    ("oidc_issuer_url", "oidc_client_id", "oidc_credentials"),
                ),
                (
                    "scim",
                    ("scim_enabled", "scim_bearer_token"),
                    ("scim_enabled", "scim_bearer_token", "scim_slug"),
                ),
                (
                    "xaa",
                    ("id_jag_issuer_url", "id_jag_jwks_url", "id_jag_allowed_clients"),
                    ("id_jag_issuer_url", "id_jag_jwks_url", "id_jag_allowed_clients"),
                ),
            )
            for scope, presence_fields, copied_fields in scopes:
                if not any(getattr(config, field) for field in presence_fields):
                    continue

                scoped_config = IdentityProviderConfig.objects.using(db_alias).create(
                    **shared,
                    config_scope=scope,
                    **{field: getattr(config, field) for field in copied_fields},
                )
                IdentityProviderConfig.objects.using(db_alias).filter(pk=scoped_config.pk).update(
                    created_at=config.created_at,
                    updated_at=config.updated_at,
                )
                links = (
                    LinkedIdentityProviderConfig.objects.using(db_alias)
                    .filter(identity_provider_config_id=config.pk)
                    .values_list("organization_domain_id", flat=True)
                    .iterator(chunk_size=CHUNK_SIZE)
                )
                LinkedIdentityProviderConfig.objects.using(db_alias).bulk_create(
                    [
                        LinkedIdentityProviderConfig(
                            identity_provider_config_id=scoped_config.pk,
                            organization_domain_id=domain_id,
                        )
                        for domain_id in links
                    ],
                    batch_size=CHUNK_SIZE,
                )

                if scope == "scim":
                    SCIMProvisionedUser.objects.using(db_alias).filter(identity_provider_config_id=config.pk).update(
                        identity_provider_config_id=scoped_config.pk
                    )
                    SCIMRequestLog.objects.using(db_alias).filter(identity_provider_config_id=config.pk).update(
                        identity_provider_config_id=scoped_config.pk
                    )

            config.delete(using=db_alias)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1383_taggeditem_untrack_legacy_keys"),
        ("ee", "0063_scim_provisioned_user_config_set_null"),
    ]

    operations = [
        migrations.RunPython(split_identity_provider_config_scopes, migrations.RunPython.noop),
    ]
