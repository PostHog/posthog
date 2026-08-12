from collections.abc import Collection
from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction

import structlog

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDModel

logger = structlog.get_logger(__name__)


class DomainScope(models.TextChoices):
    ALL = "all"
    SELECTED = "selected"


class ConfigScope(models.TextChoices):
    SAML = "saml"
    SCIM = "scim"
    XAA = "xaa"


class IdentityProviderConfig(ModelActivityMixin, UUIDModel):
    """
    Identity provider (IdP) configuration for an organization.

    Groups IdP-specific settings — SAML, SCIM, and ID-JAG (XAA) today, custom SSO in the
    future — in one place, decoupled from any single domain. One config can be mapped to
    multiple `OrganizationDomain` rows (via `OrganizationDomain.identity_provider_config`),
    and an organization can have zero, one, or many configs.

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
    saml_relay_state = models.CharField(max_length=36, blank=True, null=True, unique=True)

    # ---- SCIM attributes ----
    scim_slug = models.CharField(max_length=36, blank=True, null=True, unique=True)
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

    _IDENTIFIER_FIELDS = ("saml_relay_state", "scim_slug")
    _loaded_identifier_values: dict[str, str | None]

    class Meta:
        verbose_name = "identity provider config"

    def __str__(self) -> str:
        return self.name or str(self.id)

    @classmethod
    def from_db(cls, db: str | None, field_names: Collection[str], values: Collection[Any]) -> "IdentityProviderConfig":
        instance = super().from_db(db, field_names, values)
        instance._loaded_identifier_values = {
            field: getattr(instance, field) for field in cls._IDENTIFIER_FIELDS if field in field_names
        }
        return instance

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self._state.adding:
            super().save(*args, **kwargs)
            self._loaded_identifier_values = {field: getattr(self, field) for field in self._IDENTIFIER_FIELDS}
            return

        update_fields = kwargs.get("update_fields")
        fields_to_preserve = [
            field
            for field in self._IDENTIFIER_FIELDS
            if getattr(self, field) is None
            and (
                (update_fields is not None and field not in update_fields)
                or (update_fields is None and getattr(self, "_loaded_identifier_values", {}).get(field) is None)
            )
        ]

        if fields_to_preserve:
            with transaction.atomic():
                persisted = type(self).objects.select_for_update().values(*fields_to_preserve).get(pk=self.pk)
                for field in fields_to_preserve:
                    setattr(self, field, persisted[field])
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        saved_identifier_fields = set(fields_to_preserve)
        if update_fields is None:
            saved_identifier_fields.update(self._IDENTIFIER_FIELDS)
        else:
            saved_identifier_fields.update(field for field in self._IDENTIFIER_FIELDS if field in update_fields)
        for field in saved_identifier_fields:
            self._loaded_identifier_values[field] = getattr(self, field)

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
