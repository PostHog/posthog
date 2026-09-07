import uuid
from typing import TYPE_CHECKING, Optional, cast

from django.contrib.postgres.fields import ArrayField
from django.db import models

import structlog

from posthog.constants import AvailableFeature
from posthog.dataclasses import frozen
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

if TYPE_CHECKING:
    from posthog.models.organization_domain import OrganizationDomain

logger = structlog.get_logger(__name__)


class DomainScope(models.TextChoices):
    ALL = "all"
    SELECTED = "selected"


DEFAULT_DOMAIN_SCOPE = DomainScope.SELECTED


@frozen
class IDJagIdentityProviderResolution:
    organization_domain: Optional["OrganizationDomain"]
    identity_provider_config: Optional["IdentityProviderConfig"]
    error: Optional[str]


def has_verified_organization_domain_q() -> models.Q:
    return models.Q(linked_identity_provider_configs__organization_domain__verified_at__isnull=False) | models.Q(
        domain_scope=DomainScope.ALL, organization__domains__verified_at__isnull=False
    )


class ConfigScope(models.TextChoices):
    SAML = "saml"
    SCIM = "scim"
    ID_JAG = (
        "xaa",
        "Xaa",
    )  # TODO: before letting people put data here, let's widen the column to 6 chars and rename this to `id_jag`


def saml_configured_q() -> models.Q:
    return ~models.Q(
        models.Q(saml_entity_id="")
        | models.Q(saml_entity_id__isnull=True)
        | models.Q(saml_acs_url="")
        | models.Q(saml_acs_url__isnull=True)
        | models.Q(saml_x509_cert="")
        | models.Q(saml_x509_cert__isnull=True)
    )


class IdentityProviderConfigQuerySet(models.QuerySet["IdentityProviderConfig"]):
    def for_scope(self, config_scope: str) -> "IdentityProviderConfigQuerySet":
        return self.filter(models.Q(config_scope=config_scope) | models.Q(config_scope__isnull=True))

    def with_verified_domain_for_email(self, email: str) -> "IdentityProviderConfigQuerySet":
        if "@" not in email:
            return self.none()

        domain = email.rsplit("@", 1)[-1]
        explicitly_linked = models.Q(
            linked_identity_provider_configs__organization_domain__domain__iexact=domain,
            linked_identity_provider_configs__organization_domain__verified_at__isnull=False,
        )
        organization_wide = models.Q(
            domain_scope=DomainScope.ALL,
            organization__domains__domain__iexact=domain,
            organization__domains__verified_at__isnull=False,
        )
        return self.filter(explicitly_linked | organization_wide).distinct()

    def saml_for_email(self, email: str) -> "IdentityProviderConfigQuerySet":
        return self.for_scope(ConfigScope.SAML).filter(saml_configured_q()).with_verified_domain_for_email(email)


class IdentityProviderConfigManager(models.Manager["IdentityProviderConfig"]):
    def get_queryset(self) -> IdentityProviderConfigQuerySet:
        return IdentityProviderConfigQuerySet(self.model, using=self._db)

    def saml_for_email(self, email: str) -> IdentityProviderConfigQuerySet:
        return self.get_queryset().saml_for_email(email)

    def get_id_jag_for_request(self, email: str, issuer: str) -> IDJagIdentityProviderResolution:
        normalized_issuer = (issuer or "").rstrip("/")
        issuer_configs = (
            self.get_queryset()
            .for_scope(ConfigScope.ID_JAG)
            .annotate(
                normalized_id_jag_issuer_url=models.Func(
                    "id_jag_issuer_url",
                    models.Value("/"),
                    function="RTRIM",
                    output_field=models.CharField(),
                )
            )
            .filter(normalized_id_jag_issuer_url=normalized_issuer)
        )

        matching: list[tuple[IdentityProviderConfig, OrganizationDomain]] = []
        if "@" in email:
            domain = email.rsplit("@", 1)[-1]
            for config in issuer_configs:
                verified_domains = config.organization_domains.filter(domain__iexact=domain, verified_at__isnull=False)
                matching.extend((config, organization_domain) for organization_domain in verified_domains)

        if not matching:
            return IDJagIdentityProviderResolution(
                organization_domain=None,
                identity_provider_config=None,
                error="ID-JAG email domain is not a verified domain associated with this IdP configuration",
            )

        if len(matching) > 1:
            return IDJagIdentityProviderResolution(
                organization_domain=None,
                identity_provider_config=None,
                error="ID-JAG configuration is ambiguous: multiple configurations match this request",
            )

        config, organization_domain = matching[0]
        return IDJagIdentityProviderResolution(
            organization_domain=organization_domain,
            identity_provider_config=config,
            error=None,
        )

    def get_is_saml_available_for_email(self, email: str) -> bool:
        configs = self.get_queryset().saml_for_email(email).select_related("organization")
        return any(config.organization.is_feature_available(AvailableFeature.SAML) for config in configs)


class IdentityProviderConfig(ModelActivityMixin, UUIDModel):
    """
    Identity provider (IdP) configuration for an organization.

    Groups IdP-specific settings — SAML, SCIM, and ID-JAG (XAA) today, custom SSO in the
    future — in one place, decoupled from any single domain. One config can be mapped to
    multiple `OrganizationDomain` rows through `LinkedIdentityProviderConfig`, and an
    organization can have zero, one, or many configs.

    This model is the sole read/write interface for IdP settings (SAML/SCIM/ID-JAG). The legacy
    IdP columns on `OrganizationDomain` are no longer written to — they're frozen.
    """

    objects = IdentityProviderConfigManager()

    organization = models.ForeignKey(
        "posthog.Organization", on_delete=models.CASCADE, related_name="identity_provider_configs"
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name for this IdP configuration (e.g. 'Okta production').",
    )
    domain_scope = models.CharField(max_length=8, choices=DomainScope, blank=True, null=True)
    config_scope = models.CharField(max_length=4, choices=ConfigScope, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ---- SAML attributes ----
    # Field shapes mirror `OrganizationDomain` (including nullability) so existing values can be
    # migrated from the legacy domain columns without coercion.
    saml_entity_id = models.CharField(max_length=512, blank=True, null=True)
    saml_acs_url = models.CharField(max_length=512, blank=True, null=True)
    saml_x509_cert = models.TextField(blank=True, null=True)
    # Round-trips through the IdP as RelayState to route an assertion back to this config, and is
    # also the prefix of every `UserSocialAuth.uid` issued through it. Changing the value on a
    # config already in use orphans those identities, so it is assigned once and never edited.
    saml_relay_state = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        unique=True,
        default=uuid.uuid4,
    )

    # ---- SCIM attributes ----
    scim_slug = models.CharField(
        max_length=36,
        blank=True,
        null=True,
        unique=True,
        default=uuid.uuid4,
    )
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
    def effective_domain_scope(self) -> str:
        return self.domain_scope or DEFAULT_DOMAIN_SCOPE

    @property
    def applies_to_all_domains(self) -> bool:
        return self.effective_domain_scope == DomainScope.ALL

    @property
    def organization_domains(self) -> models.QuerySet["OrganizationDomain"]:
        organization_domain_model = cast(
            type["OrganizationDomain"], self._meta.apps.get_model("posthog", "OrganizationDomain")
        )
        domains = organization_domain_model.objects.filter(organization_id=self.organization_id)
        if self.applies_to_all_domains:
            return domains
        return domains.filter(linked_identity_provider_configs__identity_provider_config=self)

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
