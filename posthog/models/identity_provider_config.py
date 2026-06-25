from typing import TYPE_CHECKING, Any

from django.contrib.postgres.fields import ArrayField
from django.db import models

import structlog

from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models.organization_domain import OrganizationDomain

logger = structlog.get_logger(__name__)

# IdP-specific fields that are mirrored between `OrganizationDomain` (current source of
# truth) and `IdentityProviderConfig`. Used by the dual-write hook in
# `OrganizationDomain.save()` and the `sync_identity_provider_configs` management command.
IDP_CONFIG_SYNCED_FIELDS: tuple[str, ...] = (
    "saml_entity_id",
    "saml_acs_url",
    "saml_x509_cert",
    "scim_enabled",
    "scim_bearer_token",
    "id_jag_issuer_url",
    "id_jag_jwks_url",
    "id_jag_allowed_clients",
)


class IdentityProviderConfig(UUIDModel):
    """
    Identity provider (IdP) configuration for an organization.

    Groups IdP-specific settings — SAML, SCIM, and ID-JAG (XAA) today, custom SSO in the
    future — in one place, decoupled from any single domain. One config can be mapped to
    multiple `OrganizationDomain` rows (via `OrganizationDomain.identity_provider_config`),
    and an organization can have zero, one, or many configs.

    NOTE: While the migration to this model is in flight, `OrganizationDomain` remains the
    source of truth. Writes to a domain's IdP fields are mirrored here automatically by
    `OrganizationDomain.save()` (see `sync_identity_provider_config_from_domain`), so the
    data is consistent when reads are switched over.
    """

    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="identity_provider_configs"
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name for this IdP configuration (e.g. 'Okta production').",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- SAML attributes ----
    # Field shapes intentionally mirror `OrganizationDomain` (including nullability) so
    # values can be copied verbatim while domains remain the source of truth.
    saml_entity_id = models.CharField(max_length=512, blank=True, null=True)
    saml_acs_url = models.CharField(max_length=512, blank=True, null=True)
    saml_x509_cert = models.TextField(blank=True, null=True)

    # ---- SCIM attributes ----
    scim_enabled = models.BooleanField(default=False)
    scim_bearer_token = models.CharField(
        max_length=255, blank=True, null=True, help_text="Hashed bearer token for SCIM authentication"
    )

    # ---- ID-JAG (XAA) attributes ----
    id_jag_issuer_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Trusted IdP issuer URL for ID-JAG. Required to enable ID-JAG.",
    )
    # Defaults to `{id_jag_issuer_url}/.well-known/openid-configuration`.
    id_jag_jwks_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Override JWKS URL. Defaults to OIDC discovery on the issuer URL.",
    )
    id_jag_allowed_clients = ArrayField(
        models.CharField(max_length=256),
        default=list,
        blank=True,
        null=True,
        help_text="Allowed ID-JAG client IDs. Empty list allows any client_id.",
    )

    class Meta:
        verbose_name = "identity provider config"

    def __str__(self) -> str:
        return self.name or str(self.id)

    @property
    def has_saml(self) -> bool:
        """
        Returns whether SAML is configured. Does not validate the organization has the required license.
        """
        return bool(self.saml_entity_id) and bool(self.saml_acs_url) and bool(self.saml_x509_cert)

    @property
    def has_scim(self) -> bool:
        """
        Returns whether SCIM is configured and enabled.
        """
        return self.scim_enabled and bool(self.scim_bearer_token)

    @property
    def has_id_jag(self) -> bool:
        """
        Returns whether ID-JAG (XAA) is configured.
        """
        return bool(self.id_jag_issuer_url)


def _domain_has_any_idp_config(domain: "OrganizationDomain") -> bool:
    return (
        domain.has_saml
        or domain.scim_enabled
        or bool(domain.scim_bearer_token)
        or bool(domain.id_jag_issuer_url)
        or bool(domain.id_jag_jwks_url)
        or bool(domain.id_jag_allowed_clients)
    )


def sync_identity_provider_config_from_domain(domain: "OrganizationDomain", dry_run: bool = False) -> str:
    """
    Mirror a domain's IdP fields into its linked `IdentityProviderConfig`, creating and
    linking one if needed. `OrganizationDomain` is the source of truth until reads are
    switched over to the config model.

    Returns the action taken: "created", "updated", "unchanged", or "skipped" (domain has
    no IdP configuration and no linked config).
    """
    # Imported here to avoid a circular import with `organization_domain`, which calls
    # this function from `save()`.
    from posthog.models.organization_domain import OrganizationDomain  # noqa: PLC0415

    config = domain.identity_provider_config

    # Fail closed on a cross-org link: never mirror one organization's IdP settings into
    # another organization's config. A linked config must belong to the same organization
    # as the domain, otherwise saving the domain (or the backfill command) would silently
    # overwrite the other org's SAML/SCIM/XAA settings — an authentication-bypass vector.
    if config is not None and config.organization_id != domain.organization_id:
        raise ValueError(
            f"OrganizationDomain {domain.pk} (organization {domain.organization_id}) is linked to "
            f"IdentityProviderConfig {config.pk} owned by a different organization "
            f"({config.organization_id}); refusing to mirror IdP settings across organizations."
        )

    if config is None:
        if not _domain_has_any_idp_config(domain):
            return "skipped"
        if dry_run:
            return "created"
        config = IdentityProviderConfig.objects.create(
            organization_id=domain.organization_id,
            name=domain.domain,
            **{field: getattr(domain, field) for field in IDP_CONFIG_SYNCED_FIELDS},
        )
        # Link via a queryset update to avoid recursing into `OrganizationDomain.save()`
        # (and to avoid emitting a second activity log entry for the same write).
        OrganizationDomain.objects.filter(pk=domain.pk).update(identity_provider_config=config)
        domain.identity_provider_config = config
        return "created"

    changed_fields: dict[str, Any] = {
        field: getattr(domain, field)
        for field in IDP_CONFIG_SYNCED_FIELDS
        if getattr(config, field) != getattr(domain, field)
    }
    if not changed_fields:
        return "unchanged"
    if dry_run:
        return "updated"
    for field, value in changed_fields.items():
        setattr(config, field, value)
    config.save(update_fields=[*changed_fields.keys(), "updated_at"])
    return "updated"
