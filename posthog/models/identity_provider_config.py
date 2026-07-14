from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models

import structlog

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

logger = structlog.get_logger(__name__)


class IdentityProviderConfigKind(models.TextChoices):
    SAML = "saml", "SAML"
    SCIM = "scim", "SCIM"
    ID_JAG = "id_jag", "XAA"


class IdentityProviderConfig(ModelActivityMixin, UUIDModel):
    """
    Identity provider (IdP) configuration for an organization.

    Groups IdP-specific settings — SAML, SCIM, and ID-JAG (XAA) today, custom SSO in the
    future — in one place, decoupled from any single domain. One config can be mapped to
    multiple `OrganizationDomain` rows through typed `IdentityProviderConfigDomain` mappings,
    and an organization can have zero, one, or many configs for each supported feature.

    This model is the sole read/write interface for IdP settings (SAML/SCIM/ID-JAG). The legacy
    IdP columns on `OrganizationDomain` are no longer written to — they're frozen.
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
    # Field shapes intentionally mirror the legacy `OrganizationDomain` fields so existing
    # values can be copied without lossy transformations during the rollout.
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


class IdentityProviderConfigDomain(UUIDModel):
    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="identity_provider_config_domain_mappings"
    )
    identity_provider_config = models.ForeignKey(
        IdentityProviderConfig, on_delete=models.CASCADE, related_name="domain_mappings"
    )
    organization_domain = models.ForeignKey(
        "posthog.OrganizationDomain", on_delete=models.CASCADE, related_name="identity_provider_config_mappings"
    )
    kind = models.CharField(max_length=16, choices=IdentityProviderConfigKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "identity provider config domain mapping"
        constraints = [
            models.UniqueConstraint(
                fields=("organization_domain", "kind"), name="unique_idp_config_kind_per_organization_domain"
            ),
        ]

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.identity_provider_config_id and self.identity_provider_config.organization_id != self.organization_id:
            errors["identity_provider_config"] = "The identity provider config must belong to this organization."
        if self.organization_domain_id and self.organization_domain.organization_id != self.organization_id:
            errors["organization_domain"] = "The organization domain must belong to this organization."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)
