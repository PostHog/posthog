import secrets
from typing import Optional

from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.utils import timezone

import structlog
import dns.resolver

from posthog.constants import AvailableFeature
from posthog.models import Organization
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.identity_provider_config import (
    IDP_CONFIG_SYNCED_FIELDS,
    IdentityProviderConfig,
    sync_identity_provider_config_from_domain,
)
from posthog.models.utils import UUIDTModel
from posthog.utils import get_instance_available_sso_providers

logger = structlog.get_logger(__name__)


def generate_verification_challenge() -> str:
    return secrets.token_urlsafe(32)


class OrganizationDomainManager(models.Manager):
    def verified_domains(self):
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        # `select_related` the IdP config since reads of SAML/SCIM/ID-JAG settings resolve through
        # it (`OrganizationDomain.idp_config`) in the hot auth paths.
        return self.exclude(verified_at__isnull=True).select_related("identity_provider_config")

    def get_verified_for_email_address(self, email: str) -> Optional["OrganizationDomain"]:
        """
        Returns an `OrganizationDomain` configuration for a specific email address (if it exists and is verified),
        using the domain of the email address
        """
        domain = email[email.index("@") + 1 :]
        return self.verified_domains().filter(domain__iexact=domain).first()

    def get_verified_for_email_address_and_issuer(
        self, email: str, issuer: str
    ) -> tuple[Optional["OrganizationDomain"], Optional[str]]:
        """
        Resolve the `OrganizationDomain` that should authorize an ID-JAG
        assertion for `email` signed by `issuer`. Returns
        `(org_domain, error)` where `error` is `None` on success or a
        human-readable description of the failure mode otherwise.

        Lookup is by `(domain, issuer)` (not `.first()`) so the chosen org is
        deterministic and cannot be steered by row ordering when multiple
        organizations have verified the same domain. The returned org is the
        one whose IdP signed the assertion — callers should scope the issued
        access token to that org and require user membership there.
        """
        if "@" not in email:
            return None, "ID-JAG sub email domain is not a verified domain for any PostHog organization"
        domain = email[email.index("@") + 1 :].lower()
        normalized_issuer = (issuer or "").rstrip("/")

        verified_for_domain = list(self.verified_domains().filter(domain__iexact=domain))
        if not verified_for_domain:
            return None, "ID-JAG sub email domain is not a verified domain for any PostHog organization"

        configured = [d for d in verified_for_domain if (d.idp_config.id_jag_issuer_url or "").rstrip("/")]
        if not configured:
            return None, "ID-JAG is not configured for this domain (id_jag_issuer_url is unset)"

        matching = [d for d in configured if (d.idp_config.id_jag_issuer_url or "").rstrip("/") == normalized_issuer]
        if not matching:
            return None, "ID-JAG iss does not match the IdP configured for this email's domain"

        if len(matching) > 1:
            # Ambiguous config — multiple orgs verified the same domain AND
            # configured the same IdP issuer. This is a case that will rqeuire
            # manual intervention to resolve since it is not clear if one of
            # or both of the org domains are valid
            return None, "ID-JAG configuration is ambiguous: multiple OrganizationDomains share this (domain, issuer)"

        return matching[0], None

    def get_is_saml_available_for_email(self, email: str) -> bool:
        """
        Returns whether SAML is available for a specific email address.
        """
        domain = email[email.index("@") + 1 :]
        # SAML config is read from the linked `IdentityProviderConfig`. A domain with no linked
        # config produces NULLs across the LEFT JOIN, so the `__isnull=True` excludes drop it.
        query = (
            self.verified_domains()
            .filter(domain__iexact=domain)
            .exclude(
                models.Q(identity_provider_config__saml_entity_id="")
                | models.Q(identity_provider_config__saml_acs_url="")
                | models.Q(identity_provider_config__saml_x509_cert="")
                | models.Q(identity_provider_config__isnull=True)
                | models.Q(
                    identity_provider_config__saml_entity_id__isnull=True
                )  # normally we would have just a nil state (i.e. ""), but to avoid migration locks we had to introduce this
                | models.Q(identity_provider_config__saml_acs_url__isnull=True)
                | models.Q(identity_provider_config__saml_x509_cert__isnull=True)
            )
            .values_list("organization__available_product_features", flat=True)
            .first()
        )

        if query is None:
            return False

        for feature in query:
            if feature.get("key") == AvailableFeature.SAML:
                return True
        return False

    def get_sso_enforcement_for_email_address(
        self, email: str, organization: Organization | None = None
    ) -> Optional[str]:
        """
        Returns the specific `sso_enforcement` applicable for an email address or an `OrganizationDomain` objects.
        Validates SSO providers are properly configured and all the proper licenses exist.
        """
        domain = email[email.index("@") + 1 :]
        queryset = self.verified_domains().filter(domain__iexact=domain).exclude(sso_enforcement="")

        if organization is not None:
            queryset = queryset.filter(organization=organization)

        query = queryset.values(
            "sso_enforcement", "organization_id", "organization__available_product_features"
        ).first()

        if not query:
            return None

        candidate_sso_enforcement = query["sso_enforcement"]

        available_product_features = query["organization__available_product_features"]
        available_product_feature_keys = [feature["key"] for feature in available_product_features]
        # Check organization has a license to enforce SSO
        if AvailableFeature.SSO_ENFORCEMENT not in available_product_feature_keys:
            logger.warning(
                f"🤑🚪 SSO is enforced for domain {domain} but the organization does not have the proper license.",
                domain=domain,
                organization=str(query["organization_id"]),
            )
            return None

        # Check SSO provider is properly configured and has a valid license (to use the specific SSO) if applicable
        if candidate_sso_enforcement == "saml":
            # SAML uses special handling because it's configured at the domain level instead of at the instance-level
            if AvailableFeature.SAML not in available_product_feature_keys:
                logger.warning(
                    f"🤑🚪 SAML SSO is enforced for domain {domain} but the organization does not have a SAML license.",
                    domain=domain,
                    organization=str(query["organization_id"]),
                )
                return None
        else:
            sso_providers = get_instance_available_sso_providers()
            if not sso_providers[candidate_sso_enforcement]:
                logger.warning(
                    f"SSO is enforced for domain {domain} but the SSO provider ({candidate_sso_enforcement}) is not properly configured.",
                    domain=domain,
                    candidate_sso_enforcement=candidate_sso_enforcement,
                )
                return None

        return candidate_sso_enforcement


class OrganizationDomain(ModelActivityMixin, UUIDTModel):
    objects: OrganizationDomainManager = OrganizationDomainManager()

    activity_logging_on_delete = True

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=128, unique=True)
    verification_challenge = models.CharField(max_length=128, default=generate_verification_challenge)
    verified_at = models.DateTimeField(
        null=True, blank=True, default=None
    )  # verification (through DNS) is only used for PostHog Cloud; on self-hosted we take all domains as verified
    last_verification_retry = models.DateTimeField(null=True, blank=True, default=None)
    jit_provisioning_enabled = models.BooleanField(
        default=False
    )  # Just-in-time automatic provisioning (user accounts are created on the respective org when logging in with any SSO provider)
    sso_enforcement = models.CharField(
        max_length=28, blank=True
    )  # currently only used for PostHog Cloud; SSO enforcement on self-hosted is set by env var

    # ---- SAML / SCIM / ID-JAG attributes ----
    # These are mirrored from the linked `IdentityProviderConfig`, which is the source of truth
    # for reads. The Python attributes are underscore-prefixed to discourage direct access — read
    # through `self.idp_config` instead — while `db_column` keeps the original column names so no
    # schema change is needed. Only the internal sync code (and the dual-write domain serializer)
    # touches these directly.
    # Normally not good practice to have `null=True` in `CharField` (as you have to nil states now), but creating non-nullable
    # attributes locks up tables when migrating. Remove `null=True` on next major release.
    _saml_entity_id = models.CharField(max_length=512, blank=True, null=True, db_column="saml_entity_id")
    _saml_acs_url = models.CharField(max_length=512, blank=True, null=True, db_column="saml_acs_url")
    _saml_x509_cert = models.TextField(blank=True, null=True, db_column="saml_x509_cert")

    _scim_enabled = models.BooleanField(default=False, db_column="scim_enabled")
    _scim_bearer_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Hashed bearer token for SCIM authentication",
        db_column="scim_bearer_token",
    )

    _id_jag_issuer_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Trusted IdP issuer URL for ID-JAG. Required to enable ID-JAG on this domain.",
        db_column="id_jag_issuer_url",
    )
    # Defaults to `{id_jag_issuer_url}/.well-known/openid-configuration`.
    _id_jag_jwks_url = models.CharField(
        max_length=512,
        blank=True,
        null=True,
        help_text="Override JWKS URL. Defaults to OIDC discovery on the issuer URL.",
        db_column="id_jag_jwks_url",
    )
    _id_jag_allowed_clients = ArrayField(
        models.CharField(max_length=256),
        default=list,
        blank=True,
        null=True,
        help_text="Allowed ID-JAG client IDs. Empty list allows any client_id.",
        db_column="id_jag_allowed_clients",
    )

    # ---- IdP config (new home for SAML/SCIM/ID-JAG settings) ----
    # Temporary foreign key to the backing `IdentityProviderConfig` model. Eventually
    # will be removed once the migration is complete.
    # The IdP fields above are being migrated to `IdentityProviderConfig`, which can be
    # shared by multiple domains. Until reads are switched over, this model remains the
    # source of truth and `save()` mirrors the fields into the linked config.
    identity_provider_config = models.ForeignKey(
        IdentityProviderConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="domains",
        help_text="IdP configuration (SAML/SCIM/XAA) backing this domain.",
    )

    class Meta:
        verbose_name = "domain"

    def save(self, *args, **kwargs) -> None:
        # Atomic so the domain write and the mirrored IdP config write cannot diverge.
        with transaction.atomic():
            # When a brand-new domain is linked to an already-populated config, adopt the config's
            # values onto the domain's columns first. Otherwise the forward mirror would see the
            # new domain's empty columns as a "change" and blank the (possibly shared) config. This
            # mirrors the adopt-on-link the serializer does for updates; here it covers creation
            # (including direct ORM creates).
            if self._state.adding and self.identity_provider_config_id is not None:
                config = self.identity_provider_config
                for field in IDP_CONFIG_SYNCED_FIELDS:
                    setattr(self, f"_{field}", getattr(config, field))
            super().save(*args, **kwargs)
            sync_identity_provider_config_from_domain(self)

    def clean(self) -> None:
        # Validate ID-JAG IdP URLs at write time as a UX guard against the
        # common admin mistake of pointing them at an internal/loopback/
        # metadata host. This is best-effort — DNS rebinding and post-write
        # config changes can still produce an unsafe URL at fetch time, so
        # `posthog.api.id_jag._get_jwks_client` re-validates before every
        # network call. Callers must invoke `full_clean()` (or use a
        # ModelForm / DRF serializer that does) for this to take effect.
        # Imported lazily to keep this app's import graph free of security/.
        from django.core.exceptions import ValidationError

        from posthog.security.url_validation import is_url_allowed

        errors: dict[str, str] = {}
        for field_name in ("_id_jag_issuer_url", "_id_jag_jwks_url"):
            url = getattr(self, field_name, None)
            if not url:
                continue
            allowed, reason = is_url_allowed(url)
            if not allowed:
                errors[field_name] = f"URL is not allowed: {reason}"
        # A linked IdP config must belong to the same organization as the domain. Without
        # this, an admin could link a domain to another org's config and have its IdP
        # settings silently overwritten on save (see `sync_identity_provider_config_from_domain`).
        if self.identity_provider_config_id is not None:
            try:
                config = self.identity_provider_config
            except IdentityProviderConfig.DoesNotExist:
                config = None
            if config is None:
                errors["identity_provider_config"] = "IdP configuration does not exist."
            elif config.organization_id != self.organization_id:
                errors["identity_provider_config"] = (
                    "IdP configuration must belong to the same organization as the domain."
                )
        if errors:
            raise ValidationError(errors)
        super().clean()

    @property
    def is_verified(self) -> bool:
        """
        Determines whether a domain is verified or not.
        """
        # TODO: Verification becomes stale on Cloud if not reverified after a certain period.
        return bool(self.verified_at)

    @property
    def idp_config(self) -> IdentityProviderConfig:
        """
        The linked `IdentityProviderConfig` (source of truth for SAML/SCIM/ID-JAG reads), or an
        empty in-memory config when none is linked yet so reads resolve to safe empty values
        without null-guards.
        """
        return self.identity_provider_config or IdentityProviderConfig()

    @property
    def has_saml(self) -> bool:
        """
        Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places).
        """
        return self.idp_config.has_saml

    @property
    def has_scim(self) -> bool:
        """
        Returns whether SCIM is configured and enabled for this domain.
        """
        return self.idp_config.has_scim

    @property
    def has_id_jag(self) -> bool:
        """
        Returns whether ID-JAG (XAA) is configured for this domain.
        """
        return self.idp_config.has_id_jag

    def _complete_verification(self) -> tuple["OrganizationDomain", bool]:
        self.last_verification_retry = None
        self.verified_at = timezone.now()
        self.save()
        return (self, True)

    def attempt_verification(self) -> tuple["OrganizationDomain", bool]:
        """
        Performs a DNS verification for a specific domain.
        """
        try:
            # TODO: Should we manually validate DNSSEC?
            dns_response = dns.resolver.resolve(f"_posthog-challenge.{self.domain}", "TXT")
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass
        else:
            for item in list(dns_response.response.answer[0]):
                if item.strings[0].decode() == self.verification_challenge:
                    return self._complete_verification()

        self.last_verification_retry = timezone.now()
        self.save()
        return (self, False)
