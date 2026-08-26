import enum
import uuid
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.signals import user_logged_out
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import Q
from django.dispatch import receiver
from django.utils import timezone

import structlog
from oauth2_provider.generators import generate_client_id
from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
)
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.validators import AllowedURIValidator

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDT, generate_random_token, hash_key_value, mask_key_value

if TYPE_CHECKING:
    from posthog.models import Organization, User

    # This model loads at django.setup() in every process; the pydantic schema is
    # runtime-imported in the accessors that materialize it.
    from posthog.models.oauth_provisioning import PartnerTier, ProvisioningConfig


class OAuthApplicationAccessLevel(enum.Enum):
    ALL = "all"
    ORGANIZATION = "organization"
    TEAM = "team"


class OAuthApplicationAuthBrand(enum.Enum):
    POSTHOG = "posthog"
    TWIG = "twig"


class TokenEndpointAuthMethod(enum.Enum):
    """How a client authenticates at the token endpoint, per RFC 7591 section 2.

    ``NONE`` is a public client: it holds no credential and relies on PKCE (RFC 7636).
    ``CLIENT_SECRET_POST`` holds a shared secret; RFC 6749 section 2.3.1 also defines a
    ``client_secret_basic`` variant, which is not registered separately here because both
    transports are accepted from any secret-holding client. ``PRIVATE_KEY_JWT`` is
    asymmetric: the client signs an assertion (RFC 7523) that is verified against a public
    key it publishes at its ``jwks_uri``, so no shared secret ever has to be transmitted.
    """

    NONE = "none"
    CLIENT_SECRET_POST = "client_secret_post"
    PRIVATE_KEY_JWT = "private_key_jwt"


def is_loopback_host(hostname: str | None) -> bool:
    """Check if hostname is a loopback address (localhost, 127.0.0.0/8, or ::1)."""
    if not hostname:
        return False
    if hostname in ("localhost", "::1", "[::1]"):
        return True
    # Check for IPv4 loopback range 127.0.0.0/8
    if hostname.startswith("127.") and hostname.count(".") == 3:
        parts = hostname.split(".")
        if len(parts) == 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            return True
    return False


class OAuthApplication(ModelActivityMixin, AbstractApplication):  # type: ignore[django-manager-missing]
    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    # Overrides the abstract base's max_length=100 so the column can hold a CIMD
    # metadata-document URL as the client's identifier (sized to match cimd_metadata_url).
    # Non-CIMD clients keep the generated opaque value.
    client_id: models.CharField = models.CharField(
        max_length=2048, unique=True, default=generate_client_id, db_index=True
    )

    # NOTE: By default an application should be linked to the organization that created it.
    # It can be null if the organization that created it is deleted, or it was created outside of an organization (e.g. using dynamic client registration)
    # Only admins of the organization should have permission to edit the application.
    organization: "Organization | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="oauth_applications"
    )

    # NOTE: The user that created the application. It should not be used to check for access to the application, since the user might have left the organization.
    user: "User | None" = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)  # type: ignore[assignment]  # ty: ignore[invalid-assignment]

    logo_uri: models.URLField = models.URLField(
        max_length=2048, null=True, blank=True, help_text="URL to the client's logo image"
    )

    # DCR (Dynamic Client Registration) fields - RFC 7591
    is_dcr_client: models.BooleanField = models.BooleanField(
        default=False,
        verbose_name="Is DCR client",
        help_text="True if this client was registered via Dynamic Client Registration",
    )
    dcr_client_id_issued_at: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, help_text="When the client_id was issued (for DCR clients)"
    )

    # Verification status - manually set by PostHog staff
    is_verified: models.BooleanField = models.BooleanField(
        default=False, help_text="True if this application has been verified by PostHog"
    )

    # First-party flag - manually set by PostHog staff
    # First-party apps skip the OAuth consent screen and can use direct token exchange
    is_first_party: models.BooleanField = models.BooleanField(
        default=False, help_text="True if this is a first-party PostHog application that skips OAuth consent"
    )

    auth_brand: models.CharField = models.CharField(
        max_length=32,
        choices=[(brand.value, brand.value) for brand in OAuthApplicationAuthBrand],
        default=OAuthApplicationAuthBrand.POSTHOG.value,
        help_text="Branding to use on authentication pages",
    )

    # Server-stored scope ceiling for tokens issued for this app.
    # CharField max_length matches PersonalAPIKey.scopes (`max_length=100`)
    # so the same `obj:action` strings fit identically across both
    # PAT and OAuth surfaces.
    scopes: ArrayField = ArrayField(
        models.CharField(max_length=100),
        default=list,
        db_default=[],
        blank=True,
        null=False,
        help_text=(
            "Required scope ceiling — strings tokens issued for this app may carry, all required and "
            "locked on the consent screen. Empty list means a broad/deferred request (the user picks freely)."
        ),
    )

    optional_scopes: ArrayField = ArrayField(
        models.CharField(max_length=100),
        default=list,
        db_default=[],
        blank=True,
        null=False,
        help_text=(
            "Additive declinable scopes layered on top of the required `scopes` base — the user may "
            "decline these at consent. Requires a non-empty `scopes` (an app with optional extras must "
            "have a required base)."
        ),
    )

    @property
    def ceiling_scopes(self) -> list[str]:
        """The full grantable set: `scopes` plus `optional_scopes`, deduplicated."""
        return list(dict.fromkeys([*self.scopes, *self.optional_scopes]))

    @property
    def required_scopes(self) -> list[str]:
        # Everything in the explicit ceiling is required and locked at consent; optional_scopes
        # are additive declinable extras. An empty `scopes` is a broad/deferred request
        # (MCP / `*` / empty) so nothing is required and the user picks freely. Self-registered
        # (DCR / CIMD) ceilings are already filtered to grantable scopes and shown as locked rows
        # the user can decline by cancelling, so they carry the same required floor as any other app.
        return list(self.scopes)

    # Generation marker for app-wide session revocation. A refresh presenting a token issued
    # before this timestamp is rejected at mint time, so a refresh racing revoke_application_sessions
    # can't slip new tokens past the one-shot bulk revoke.
    sessions_revoked_at: models.DateTimeField = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When an admin last force-revoked every session for this app. Tokens issued before this "
            "are rejected on refresh, forcing re-authorization."
        ),
    )

    # CIMD (Client ID Metadata Document) fields — draft-ietf-oauth-client-id-metadata-document-00
    is_cimd_client: models.BooleanField = models.BooleanField(
        default=False,
        verbose_name="Is CIMD client",
        help_text="True if this client was registered via Client ID Metadata Document (CIMD)",
    )
    cimd_metadata_url: models.URLField = models.URLField(
        max_length=2048,
        null=True,
        blank=True,
        unique=True,
        help_text="The URL used as client_id for CIMD clients. Must match the client_id in the metadata document.",
    )
    cimd_metadata_last_fetched: models.DateTimeField = models.DateTimeField(
        null=True, blank=True, help_text="When the CIMD metadata was last successfully fetched"
    )

    # Client authentication - RFC 7591 section 2 client metadata
    jwks_uri: models.URLField = models.URLField(
        max_length=2048,
        null=True,
        blank=True,
        help_text=(
            "HTTPS URL serving the client's public keys as a JWK Set. Setting this on a "
            "confidential client switches it to private_key_jwt authentication (RFC 7523): it "
            "signs an assertion we verify against these keys instead of holding a shared secret."
        ),
    )

    # Provisioning fields - only relevant for partners that provision accounts/resources
    # via the agentic provisioning API. Null/blank for regular OAuth clients.
    is_provisioning_partner: models.BooleanField = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "Whether this app may act as an agentic provisioning partner. How it authenticates "
            "follows from client_type, so there is no separate provisioning auth method."
        ),
    )
    # Mangled so the `provisioning` property below can own the readable name. Every capability
    # and quota lives in here; see posthog/models/oauth_provisioning.py for the shape. Empty
    # object means "a partner that may do nothing yet", which is the intended starting point.
    _provisioning_config: models.JSONField = models.JSONField(
        default=dict,
        db_default={},
        blank=True,
        db_column="provisioning_config",
        help_text=(
            "Provisioning capabilities and per-endpoint rate limits. Every capability is off unless explicitly granted."
        ),
    )

    @property
    def provisioning(self) -> "ProvisioningConfig":
        """The parsed provisioning config. Absent keys read as their default, so a partner is
        never accidentally granted a capability the stored blob never mentioned."""
        from posthog.models.oauth_provisioning import ProvisioningConfig  # noqa: PLC0415

        return ProvisioningConfig.model_validate(self._provisioning_config or {})

    @provisioning.setter
    def provisioning(self, value: "ProvisioningConfig | dict") -> None:
        from posthog.models.oauth_provisioning import ProvisioningConfig  # noqa: PLC0415

        config = value if isinstance(value, ProvisioningConfig) else ProvisioningConfig.model_validate(value)
        self._provisioning_config = config.model_dump(mode="json")

    def update_provisioning(self, **changes: object) -> "ProvisioningConfig":
        """Apply a partial change to the config and persist it.

        The blob is one column, so a read-modify-write is the only way to set a single key
        without clobbering its neighbours. That makes concurrent writers a lost-update
        problem - an admin granting a capability while a CIMD refresh re-tiers a rate limit
        would otherwise have one silently overwrite the other - so the row is locked and
        re-read inside the transaction rather than trusting the copy in memory.
        """
        with transaction.atomic():
            current = OAuthApplication.objects.select_for_update().get(pk=self.pk)
            self._provisioning_config = current._provisioning_config
            self.provisioning = self.provisioning.model_copy(update=changes)
            self.save(update_fields=["_provisioning_config"])
        return self.provisioning

    def update_provisioning_rate_limits(self, **changes: int | None) -> "ProvisioningConfig":
        """Apply a partial change to the per-endpoint rate limit overrides and persist it.

        A value of None removes the endpoint's override (back to the tier-derived
        budget). Nested under the same lock as any other partial change, so the read
        of the current limits can't be stale by the time it is written back.
        """
        with transaction.atomic():
            current = OAuthApplication.objects.select_for_update().get(pk=self.pk)
            self._provisioning_config = current._provisioning_config
            merged = {**self.provisioning.rate_limits, **changes}
            return self.update_provisioning(rate_limits={k: v for k, v in merged.items() if v is not None})

    @property
    def partner_tier(self) -> "PartnerTier":
        """See :class:`~posthog.models.oauth_provisioning.PartnerTier`. The attested
        signal is the CIMD verification-token binding (``organization_id``), the same
        one CIMD registration reads."""
        from posthog.models.oauth_provisioning import PartnerTier  # noqa: PLC0415

        attested = self.organization_id is not None
        if self.requires_client_authentication:
            return PartnerTier.JWKS_ATTESTED if attested else PartnerTier.JWKS
        return PartnerTier.PUBLIC_ATTESTED if attested else PartnerTier.PUBLIC

    @property
    def carries_provisioning_config(self) -> bool:
        """Whether this app has ever been configured for provisioning, whatever
        ``is_provisioning_partner`` says now.

        Partner quotas key on this rather than the flag, so an admin who disables a partner
        without revoking its outstanding tokens doesn't also exempt those tokens from the
        rate limits.

        "Grants or records something" rather than "the column is non-empty": the backfill writes
        a config to every row, ordinary OAuth apps included, so a non-empty blob says nothing
        about whether an app was ever a partner. A config equal to the all-default one carries no
        grant, no deactivation and no quota, which is exactly the app that owes no partner quota.
        """
        from posthog.models.oauth_provisioning import ProvisioningConfig  # noqa: PLC0415

        return self.is_provisioning_partner or self.provisioning != ProvisioningConfig()

    # Client authentication is registration state on purpose. A client_id is public, so
    # inferring the method from what a request happens to present would let anyone act as a
    # confidential client by presenting nothing at all.

    @property
    def effective_client_id(self) -> str:
        """The identifier this client uses for itself on the wire.

        For a CIMD client that is its metadata URL, which is what the client sends and what it
        names itself by in a signed assertion; the ``client_id`` column holds an opaque value
        generated at registration. For every other client the two are the same.

        Gated on ``is_cimd_client`` so a stray ``cimd_metadata_url`` on a non-CIMD app cannot
        change which identifier an assertion's ``iss``/``sub`` are checked against.
        """
        if self.is_cimd_client and self.cimd_metadata_url:
            return self.cimd_metadata_url
        return self.client_id

    @property
    def requires_client_authentication(self) -> bool:
        """Whether this client must prove itself, i.e. is confidential (RFC 6749 section 3.2.1)."""
        return self.client_type == AbstractApplication.CLIENT_CONFIDENTIAL

    @property
    def token_endpoint_auth_method(self) -> TokenEndpointAuthMethod:
        """Which RFC 7591 method this client authenticates with.

        Derived rather than stored: the client type says whether it authenticates at all, and a
        jwks_uri says it does so with an asymmetric key. Both are registration state, so this is
        never influenced by what a request presents.
        """
        if not self.requires_client_authentication:
            return TokenEndpointAuthMethod.NONE
        if self.jwks_uri:
            return TokenEndpointAuthMethod.PRIVATE_KEY_JWT
        return TokenEndpointAuthMethod.CLIENT_SECRET_POST

    @property
    def uses_client_secret_auth(self) -> bool:
        return self.token_endpoint_auth_method is TokenEndpointAuthMethod.CLIENT_SECRET_POST

    @property
    def uses_private_key_jwt_auth(self) -> bool:
        return self.token_endpoint_auth_method is TokenEndpointAuthMethod.PRIVATE_KEY_JWT

    class Meta(AbstractApplication.Meta):
        verbose_name = "OAuth Application"
        verbose_name_plural = "OAuth Applications"
        swappable = "OAUTH2_PROVIDER_APPLICATION_MODEL"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(skip_authorization=False),
                name="enforce_skip_authorization_false",
            ),
            # Note: We do not support HS256 since we don't want to store the client secret in plaintext
            models.CheckConstraint(condition=models.Q(algorithm="RS256"), name="enforce_rs256_algorithm"),
            models.CheckConstraint(
                condition=models.Q(authorization_grant_type=AbstractApplication.GRANT_AUTHORIZATION_CODE),
                name="enforce_supported_grant_types",
            ),
        ]

    # Dangerous URI schemes that could be used for attacks (XSS, data exfiltration, etc.)
    DEFAULT_BLOCKED_SCHEMES = frozenset(["javascript", "data", "file", "blob", "vbscript"])

    @staticmethod
    def get_blocked_schemes() -> set[str]:
        """Get the set of blocked redirect URI schemes from settings."""
        return set(
            cast(
                list[str],
                settings.OAUTH2_PROVIDER.get(
                    "BLOCKED_REDIRECT_URI_SCHEMES", list(OAuthApplication.DEFAULT_BLOCKED_SCHEMES)
                ),
            )
        )

    def clean(self):
        # Full override of AbstractApplication.clean(). We run django-oauth-toolkit's redirect_uri
        # validator ourselves with a carve-out for authority-less native-app schemes (com.example.app:/oauth),
        # and re-implement its remaining model checks in _validate_application_config — rather than
        # calling super().clean(), which would re-run the redirect validation and reject those native schemes.
        self._validate_redirect_uris()
        self._validate_optional_scopes()
        self._validate_client_authentication()
        self._validate_application_config()

    def _validate_client_authentication(self):
        if self.jwks_uri and not self.jwks_uri.startswith("https://"):
            raise ValidationError("jwks_uri must be an https URL")

        # A stored key set on a public client enables optional assertion authentication
        # (verify_client_assertion) without requiring it: token_endpoint_auth_method reads
        # requires_client_authentication first, so a public client derives NONE regardless
        # of jwks_uri.

    def _validate_redirect_uris(self):
        validator = AllowedURIValidator(
            {scheme.lower() for scheme in self.get_allowed_schemes()},
            name="redirect uri",
            allow_path=True,
            allow_query=True,
            allow_hostname_wildcard=oauth2_settings.ALLOW_URI_WILDCARDS,
        )
        for uri in self.redirect_uris.split():
            parsed_uri = urlparse(uri)

            # RFC 8252 Section 7.1 private-use scheme redirects (e.g. com.example.app:/oauth)
            # are authority-less by design; django-oauth-toolkit validator rejects them solely for lacking a host.
            # Everything else goes through validator unchanged.
            if parsed_uri.scheme not in ("http", "https", "") and parsed_uri.hostname is None:
                if parsed_uri.scheme in self.get_blocked_schemes():
                    raise ValidationError(
                        {
                            "redirect_uris": f"Redirect URI scheme '{parsed_uri.scheme}' is not allowed for security reasons"
                        }
                    )
                if parsed_uri.fragment:
                    raise ValidationError({"redirect_uris": f"Redirect URI {uri} cannot contain fragments"})
                continue

            # django-oauth-toolkit validates scheme, fragment, and URL shape
            validator(uri)

            # django-oauth-toolkit permits any allowlisted scheme; we additionally require https except on loopback.
            if parsed_uri.scheme == "http" and not is_loopback_host(parsed_uri.hostname):
                raise ValidationError(
                    {
                        "redirect_uris": f"Redirect URI {uri} must use https (http is only allowed for loopback addresses)"
                    }
                )

    def _validate_optional_scopes(self):
        if not self.optional_scopes:
            return
        if not self.scopes:
            raise ValidationError(
                {"optional_scopes": "Declaring optional scopes requires a non-empty required set in `scopes`."}
            )
        for field, values in (("scopes", self.scopes), ("optional_scopes", self.optional_scopes)):
            non_resource = [scope for scope in values if ":" not in scope]
            if non_resource:
                # `*` or identity scopes in a required set either brick /authorize
                # (explicit ceilings reject `*`) or 400 every consent the client
                # didn't request them on, with no UI recourse.
                raise ValidationError(
                    {
                        field: f"With optional scopes declared, every entry must be a resource scope "
                        f"(object:action); invalid: {', '.join(non_resource)}"
                    }
                )

    def _validate_application_config(self):
        # Mirror of AbstractApplication.clean()'s non-redirect checks (grant type, allowed origins,
        # signing algorithm). Re-implemented here because clean() does not call super().clean()
        code_grant_types = (
            AbstractApplication.GRANT_AUTHORIZATION_CODE,
            AbstractApplication.GRANT_IMPLICIT,
            AbstractApplication.GRANT_OPENID_HYBRID,
        )
        if not self.redirect_uris.split() and self.authorization_grant_type in code_grant_types:
            raise ValidationError(f"redirect_uris cannot be empty with grant_type {self.authorization_grant_type}")

        allowed_origins = self.allowed_origins.split()
        if allowed_origins:
            origin_validator = AllowedURIValidator(
                oauth2_settings.ALLOWED_SCHEMES,
                name="allowed origin",
                allow_hostname_wildcard=oauth2_settings.ALLOW_URI_WILDCARDS,
            )
            for origin in allowed_origins:
                origin_validator(origin)

        if self.algorithm == AbstractApplication.RS256_ALGORITHM and not oauth2_settings.OIDC_RSA_PRIVATE_KEY:
            raise ValidationError("You must set OIDC_RSA_PRIVATE_KEY to use RSA algorithm")

        if self.algorithm == AbstractApplication.HS256_ALGORITHM and (
            self.authorization_grant_type
            in (AbstractApplication.GRANT_IMPLICIT, AbstractApplication.GRANT_OPENID_HYBRID)
            or self.client_type == AbstractApplication.CLIENT_PUBLIC
        ):
            raise ValidationError("You cannot use HS256 with public grants or clients")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_allowed_schemes(self) -> list[str]:
        """Extract unique schemes from the application's registered redirect URIs, filtering out blocked schemes."""
        blocked_schemes = self.get_blocked_schemes()
        schemes: set[str] = set()
        for uri in self.redirect_uris.split(" "):
            if not uri:
                continue
            parsed_uri = urlparse(uri)
            if parsed_uri.scheme and parsed_uri.scheme not in blocked_schemes:
                schemes.add(parsed_uri.scheme)
        return list(schemes) if schemes else ["https"]


def oauth_scope_tokens_expression() -> models.Func:
    return models.Func(
        models.F("scope"),
        models.Value(" "),
        function="string_to_array",
        output_field=ArrayField(models.TextField()),
    )


class OAuthAccessToken(AbstractAccessToken):
    class Meta(AbstractAccessToken.Meta):
        verbose_name = "OAuth Access Token"
        verbose_name_plural = "OAuth Access Tokens"
        swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"
        indexes = [
            # Direct updates avoid pending-list merges that make one token write absorb batched GIN maintenance.
            GinIndex(
                oauth_scope_tokens_expression(),
                name="oauthaccesstoken_scopes_gin",
                condition=Q(application__isnull=False),
                fastupdate=False,
            ),
            # B-tree on the plaintext `token` so equality lookups by token value resolve
            # via an index scan instead of a sequential scan. These lookups account for a
            # large share of the server's CPU time; the index removes that hot-path scan.
            models.Index(fields=["token"], name="oauthaccesstoken_token_idx"),
        ]

    @classmethod
    def with_scope(cls, scope: str) -> models.QuerySet["OAuthAccessToken"]:
        return cls.objects.alias(scope_tokens=oauth_scope_tokens_expression()).filter(
            scope_tokens__contains=[scope], application_id__isnull=False
        )

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="oauth_access_tokens",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)
    # Server-minted sandbox binding: task-scoped APIs must not trust a caller-supplied task header alone.
    sandbox_task_id: models.UUIDField = models.UUIDField(null=True, blank=True)

    # When set, this token was minted by a staff user impersonating `user`. Used to revoke
    # tokens at impersonation end. SET_NULL so the customer's tokens survive admin deactivation.
    impersonated_by: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_index=True,
    )

    # Optional user-facing label set at mint time. Carried across refreshes so
    # it persists for the life of the connection, not just one rotated token.
    label: models.CharField = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_default="",
        help_text="Optional user-facing label so a user can identify a token (per-device, per-IP, or by purpose).",
    )


class OAuthIDToken(AbstractIDToken):
    class Meta(AbstractIDToken.Meta):
        verbose_name = "OAuth ID Token"
        verbose_name_plural = "OAuth ID Tokens"
        swappable = "OAUTH2_PROVIDER_ID_TOKEN_MODEL"

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="oauth_id_tokens",
    )


class OAuthRefreshToken(AbstractRefreshToken):
    class Meta(AbstractRefreshToken.Meta):
        verbose_name = "OAuth Refresh Token"
        verbose_name_plural = "OAuth Refresh Tokens"
        swappable = "OAUTH2_PROVIDER_REFRESH_TOKEN_MODEL"
        indexes = [
            # revoke_oauth_token_family sweeps by token_family on the /oauth/token path;
            # without this index the sweep scans the whole refresh token table.
            models.Index(fields=["token_family"], name="oauthrefreshtoken_family_idx"),
        ]

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: "User" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="oauth_refresh_tokens",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)

    # See OAuthAccessToken.impersonated_by — propagated through token rotation.
    impersonated_by: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_index=True,
    )


class OAuthGrant(AbstractGrant):
    class Meta(AbstractGrant.Meta):
        verbose_name = "OAuth Grant"
        verbose_name_plural = "OAuth Grants"
        swappable = "OAUTH2_PROVIDER_GRANT_MODEL"

        # Note: We do not support plaintext code challenge methods since they are not secure
        constraints = [
            models.CheckConstraint(
                condition=models.Q(code_challenge_method=AbstractGrant.CODE_CHALLENGE_S256),
                name="enforce_supported_code_challenge_method",
            )
        ]

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)

    user: "User" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="oauth_grants",
    )

    scoped_teams: ArrayField = ArrayField(models.IntegerField(), null=True, blank=True)
    scoped_organizations: ArrayField = ArrayField(models.CharField(max_length=100), null=True, blank=True)

    # See OAuthAccessToken.impersonated_by — propagated from grant to access token at code exchange.
    impersonated_by: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_index=True,
    )


def find_oauth_access_token(token: str) -> OAuthAccessToken | None:
    """Find an OAuth access token by its value using the token_checksum index."""
    from hashlib import sha256

    checksum = sha256(token.encode()).hexdigest()
    try:
        return OAuthAccessToken.objects.select_related("user", "application", "source_refresh_token").get(
            token_checksum=checksum
        )
    except OAuthAccessToken.DoesNotExist:
        return None


def find_oauth_refresh_token(token: str) -> OAuthRefreshToken | None:
    """Find an active OAuth refresh token by its value."""
    try:
        return OAuthRefreshToken.objects.select_related("user", "application", "access_token").get(
            token=token, revoked__isnull=True
        )
    except OAuthRefreshToken.DoesNotExist:
        return None


def live_oauth_access_tokens(user: "User") -> models.QuerySet[OAuthAccessToken]:
    """Access tokens an application can still present as `user`."""
    return OAuthAccessToken.objects.filter(user=user, application__isnull=False, expires__gt=timezone.now())


def live_oauth_refresh_tokens(user: "User") -> models.QuerySet[OAuthRefreshToken]:
    """Refresh tokens an application can still exchange for a new access token as `user`.

    Unrevoked is the whole test. DOT's `validate_refresh_token` checks the token value, the
    `revoked` timestamp, and the client, and never compares `created` against
    REFRESH_TOKEN_EXPIRE_SECONDS; that setting only drives the `clear_expired` cleanup job. So a
    refresh token whose access token lapsed hours ago still mints a new one on demand, which
    means it has to count as standing access anywhere we answer "who can act as this user".
    """
    return OAuthRefreshToken.objects.filter(user=user, revoked__isnull=True)


def has_live_third_party_oauth_access(user: "User") -> bool:
    """Whether any non-first-party application can act as `user` right now.

    Refresh tokens have to be counted here, because a provisioning partner holds one for the life
    of the connection and owns no live access token at all between refreshes. Checking access
    tokens alone would therefore report no access for a partner that has full standing access.

    First-party applications are excluded because they are PostHog's own surfaces, so a token from
    one is not the third-party access this answers about.
    """
    return OAuthApplication.objects.filter(
        Q(id__in=live_oauth_access_tokens(user).values("application_id"))
        | Q(id__in=live_oauth_refresh_tokens(user).values("application_id")),
        is_first_party=False,
    ).exists()


def lock_oauth_connection(*, user_id: int, application_id: uuid.UUID) -> None:
    """Serialize token minting against session revocation for one (user, application) pair.

    Revocation cannot rely on row locks alone. DOT validates a refresh token in autocommit and only
    locks the row later, inside `save_bearer_token`, so a mint can already hold that row lock when a
    revoke arrives. The revoke's sweep then blocks, and when Postgres releases it the statement
    re-checks the locked row but does not widen its snapshot, so a refresh token the mint inserted
    meanwhile stays invisible to the sweep and outlives it.

    Every party takes this lock before any row lock, so the acquisition order is identical on both
    sides and a revoke waiting on a mint's row lock cannot deadlock against a mint waiting on this
    one. See `OAuthValidator.save_bearer_token` for the minting side.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [user_id, str(application_id)])


def revoke_oauth_session(
    access_token: OAuthAccessToken | None = None, refresh_token: OAuthRefreshToken | None = None
) -> None:
    """Revoke all OAuth artifacts for the token's (user, application) pair - every access
    token, every refresh token, and every grant, not just the given one.

    Use this where the user or client explicitly asked to disconnect the whole app
    (connected_apps.py, RFC 7009 revoke_token) - there, sweeping every session for that
    (user, application) is the correct, intentional scope. For a report that ONE specific
    credential leaked, use revoke_oauth_token_session instead: a leaked token is evidence
    about that one token, not about the user's other sessions with the app.
    """
    from django.utils import timezone

    now = timezone.now()

    # Get user and application from whichever token we have
    if access_token:
        user = access_token.user
        application = access_token.application
    elif refresh_token:
        user = refresh_token.user
        application = refresh_token.application
    else:
        return

    if not user or not application:
        # The user is technically nullable, so it's possible to hit this.
        # We can't revoke the full session without user+application, but still revoke the specific token (best effort)
        if access_token:
            access_token.delete()
        if refresh_token:
            refresh_token.revoked = now
            refresh_token.save(update_fields=["revoked"])
    else:
        # Same ordering as revoke_application_sessions below, for the same two reasons:
        # grants deleted first so this blocks on a racing code exchange's grant-row lock
        # instead of missing tokens it mints; refresh tokens deleted before access tokens so a
        # mid-way failure can't leave a refresh token live after its access token is gone.
        with transaction.atomic():
            lock_oauth_connection(user_id=user.pk, application_id=application.pk)

            # Delete all grants for this user+application
            OAuthGrant.objects.filter(user=user, application=application).delete()

            # Delete, rather than revoke, every refresh token for this user+application. Absence is
            # what makes the revoke stick: `validate_refresh_token` looks a token up by value and
            # rejects a miss, whereas a row marked `revoked` keeps validating for
            # REFRESH_TOKEN_GRACE_PERIOD_SECONDS and then mints a replacement pair, because
            # `RefreshToken.revoke()` returns silently on an already-revoked row. Deleting covers a
            # token rotation already revoked too, which a `revoked__isnull=True` filter would skip
            # while the grace period still accepts it.
            OAuthRefreshToken.objects.filter(user=user, application=application).delete()

            # Delete all access tokens for this user+application
            OAuthAccessToken.objects.filter(user=user, application=application).delete()


def revoke_oauth_token_family(refresh_token: OAuthRefreshToken) -> None:
    """Revoke every live member of a refresh token's family in a constant number of
    queries, and delete the access tokens still linked to them.

    Use this when refresh-token reuse protection fires and the whole family is suspect:
    DOT's per-row `RefreshToken.revoke()` loop costs a `SELECT ... FOR UPDATE` per family
    member, even already-revoked ones.

    This reproduces the effects of upstream's `AbstractRefreshToken.revoke` (stamp
    `revoked`, delete the linked access token) in bulk, so any new effect upstream adds to
    `revoke()` must be mirrored here. `posthog/api/oauth/test_oauth_validator_fork.py`
    pins that upstream source and fails when it changes."""
    # Rows without a family (pre-rotation-refresh tokens, non-rotating clients) are their
    # own lineage: sweeping them by token_family=None would revoke unrelated tokens.
    if refresh_token.token_family is None:
        return
    now = timezone.now()
    with transaction.atomic():
        # Revoke refresh tokens before deleting access tokens, in one transaction, so a
        # mid-way failure can't leave one of them live after its access token is gone
        # (same ordering as revoke_oauth_session above). The delete joins through the
        # subquery instead of listing ids in Python: reuse protection fires rarely, but
        # a compromised family can hold tens of thousands of historical rows.
        OAuthRefreshToken.objects.filter(token_family=refresh_token.token_family, revoked__isnull=True).update(
            revoked=now
        )
        OAuthAccessToken.objects.filter(refresh_token__token_family=refresh_token.token_family).delete()


def _refresh_token_may_have_untracked_access_tokens(refresh_token: OAuthRefreshToken) -> bool:
    """True for a non-rotating refresh token (DCR/CIMD clients - see
    OAuthTokenView._save_bearer_token in posthog/api/oauth/views.py), which inserts a new,
    unlinked OAuthAccessToken row on every refresh instead of updating one access token in
    place. Those rows carry no queryable link back to the refresh token that minted them
    (source_refresh_token is left None specifically so sibling rows stay addressable), so
    there's no way to enumerate every access token a given non-rotating refresh token could
    have produced.
    """
    application = refresh_token.application
    if application.is_dcr_client or application.is_cimd_client:
        return True
    return not oauth2_settings.ROTATE_REFRESH_TOKEN


def revoke_oauth_token_session(
    access_token: OAuthAccessToken | None = None, refresh_token: OAuthRefreshToken | None = None
) -> None:
    """Revoke only the one access/refresh token pair the given token belongs to, not
    every session the user has with the application.

    Use this for a report that identifies ONE specific leaked credential (github.py, the
    public leaked-key endpoint) - see revoke_oauth_session for where the broader sweep is
    the correct, intentional scope instead.

    Doesn't touch OAuthGrant: a grant is a single-use authorization code consumed at
    token exchange, not part of an ongoing session, so there's no "this token's grant" to
    revoke alongside it.
    """
    from django.utils import timezone

    now = timezone.now()

    if access_token:
        # Neither direction of the access_token <-> refresh_token OneToOne is reliably
        # populated on its own (our non-rotating _save_bearer_token branch leaves
        # source_refresh_token None - see revoke_token's docstring in
        # posthog/api/oauth/views.py - and callers that create a refresh token before
        # its access token don't always back-fill refresh_token.access_token either), so
        # check both directions instead of trusting one.
        #
        # Revoke the refresh token before deleting the access token, in one transaction,
        # so a mid-way failure can't leave the refresh token live after its access token
        # is already gone (same reasoning as revoke_application_sessions below).
        with transaction.atomic():
            OAuthRefreshToken.objects.filter(
                Q(access_token=access_token) | Q(pk=access_token.source_refresh_token_id), revoked__isnull=True
            ).update(revoked=now)
            access_token.delete()
    elif refresh_token:
        if _refresh_token_may_have_untracked_access_tokens(refresh_token):
            # A leaked non-rotating refresh token can have minted any number of access
            # tokens with no durable link back to it (see
            # _refresh_token_may_have_untracked_access_tokens), so a per-token revoke can't
            # guarantee all of them are caught. Fall back to the same (user, application)
            # sweep revoke_token already uses for this exact case via RFC 7009.
            revoke_oauth_session(refresh_token=refresh_token)
            return
        # Revoke before deleting the linked access token(s), in one transaction, so a
        # mid-way failure can't leave this refresh token live (and able to mint a new
        # access token) after its access token is already gone.
        with transaction.atomic():
            refresh_token.revoked = now
            refresh_token.save(update_fields=["revoked"])
            OAuthAccessToken.objects.filter(
                Q(pk=refresh_token.access_token_id) | Q(source_refresh_token=refresh_token)
            ).delete()


def revoke_application_sessions(application: "OAuthApplication") -> None:
    """Force-invalidate every outstanding token and grant for an application, across all users.

    Lets a scope-ceiling narrowing take effect immediately by forcing every connection to
    re-authorize under the new ceiling, instead of waiting for each token to hit its next
    refresh (where `get_original_scopes` caps it).

    Revokes refresh tokens before deleting access tokens, all in one transaction, so a
    concurrent refresh can't mint a fresh access token in the gap and a mid-way failure
    can't leave refresh tokens live after their access tokens are already gone.

    Stamps `sessions_revoked_at` so a refresh that validated its (now-revoked) token before
    this transaction committed is rejected when it tries to mint — DOT validates the refresh
    token in autocommit, before its own transaction takes the row lock, so the bulk update
    here would otherwise miss the tokens that racing refresh is about to create.

    Grants are deleted before the token sweep: a racing code exchange locks its grant row at
    mint (`_reject_code_exchange_racing_revoke`), so deleting grants first makes this
    transaction block on that lock and re-snapshot the token sweep after the mint commits.
    Sweeping tokens first would let the racing mint's tokens escape the sweep."""
    now = timezone.now()
    with transaction.atomic():
        OAuthApplication.objects.filter(pk=application.pk).update(sessions_revoked_at=now)
        OAuthGrant.objects.filter(application=application).delete()
        OAuthRefreshToken.objects.filter(application=application, revoked__isnull=True).update(revoked=now)
        OAuthAccessToken.objects.filter(application=application).delete()


def generate_random_token_cimd_verification() -> str:
    return "phvt_" + generate_random_token()


# Never a real normalized URL, so it only ever equals another call that hit the same
# unparseable-input branch. Issuance validates and normalizes before storing (see
# `CIMDVerificationTokenCreateSerializer` in posthog/api/cimd_verification_token.py), so no
# stored `CIMDVerificationToken.cimd_url` can ever equal this — it exists only to give the
# refresh path (which normalizes `OAuthApplication.cimd_metadata_url` read straight from the
# database, unrevalidated) a value to compare against instead of raising.
UNNORMALIZABLE_CIMD_URL = "\x00unnormalizable"


def normalize_cimd_url(url: str) -> str:
    """Canonicalize a CIMD URL so issuance and verification compare equal.

    Both sides store/compare the output of this function, so the only thing that
    matters is that it is deterministic and collapses the variations a partner
    can plausibly produce for the same document: scheme and host case, an
    explicit `:443` (and `:0` — `port and port != 443` treats a falsy port the same as
    "no port"), and any number of trailing slashes. Reconstructing from `parsed.path`
    also drops a `;params` segment `urlparse` splits off the last path element, so
    `.../x.json`, `.../x.json;evil`, and `.../x.json///` all collapse to the same value.
    This is canonicalization for a database comparison, not a security boundary:
    `fetch_cimd_metadata` still requires `client_id == url` byte for byte against the
    real fetch URL.

    Deliberately does not touch path case or percent-encoding — those are
    server-defined and two paths differing there are legitimately different
    documents.

    The output is a persisted format, not just a comparison helper: it is stored in
    `CIMDVerificationToken.cimd_url`, and migration
    `1296_backfill_cimd_verification_token_url` keeps a frozen copy of this function's
    logic. Changing this function's output for any input silently unverifies every
    stored binding of that shape with no test failure elsewhere — see the golden-value
    table in `TestNormalizeCimdUrl` (posthog/models/test/test_oauth.py) before editing.
    """
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError:
        # Covers both an unparseable port ("h:abc", "h:99999") and a urlparse failure on
        # the whole URL ("https://[::1/x.json" raises "Invalid IPv6 URL"). Nothing can be
        # served at either, so a sentinel that matches no real fetch is enough.
        return UNNORMALIZABLE_CIMD_URL
    host = (parsed.hostname or "").lower()
    if port and port != 443:
        host = f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{host}{path}"


class CIMDVerificationToken(models.Model):
    """Token that links a CIMD partner app to a PostHog organization.

    A partner embeds the plaintext token in their CIMD metadata document under
    `posthog_verification_token`. On fetch, we hash and look up the token; if it
    matches AND the document URL equals `cimd_url`, we link the resulting
    OAuthApplication to this organization and apply the verified-partner
    rate-limit tier.

    The token is served unauthenticated at the metadata URL, so possession of it
    proves nothing — anyone who reads the document can host the same value
    elsewhere. `cimd_url` is what makes the token unforgeable: it scopes the
    token to the one document it was issued for, so a copy hosted anywhere else
    fails to verify.

    `cimd_url` is deliberately NOT unique. Uniqueness would let anyone with a
    free organization reserve a partner's URL before that partner does and lock
    them out of verification permanently. Several organizations may claim the
    same URL; only the one whose token actually appears in the document at that
    URL verifies.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    organization: "Organization" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.Organization", on_delete=models.CASCADE, related_name="cimd_verification_tokens"
    )
    label: models.CharField = models.CharField(max_length=40)
    cimd_url: models.URLField = models.URLField(max_length=2048, null=True, blank=True)
    mask_value: models.CharField = models.CharField(max_length=11, editable=False, null=True)
    secure_value: models.CharField = models.CharField(unique=True, max_length=300, editable=False)
    created_by: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    last_used_at: models.DateTimeField = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "CIMD Verification Token"
        verbose_name_plural = "CIMD Verification Tokens"


def find_cimd_verification_token(token: str) -> "CIMDVerificationToken | None":
    if not token or not token.startswith("phvt_"):
        return None
    secure_value = hash_key_value(token)
    try:
        return CIMDVerificationToken.objects.select_related("organization").get(secure_value=secure_value)
    except CIMDVerificationToken.DoesNotExist:
        return None


def create_cimd_verification_token(
    *, organization: "Organization", label: str, cimd_url: str, created_by: "User | None" = None
) -> tuple[CIMDVerificationToken, str]:
    """Create a new token, returning (instance, plaintext). Plaintext is only
    available at creation time — we only persist its hash.

    `cimd_url` is stored normalized so verification can compare it to the fetch
    URL as an exact string."""
    plaintext = generate_random_token_cimd_verification()
    token = CIMDVerificationToken.objects.create(
        organization=organization,
        label=label,
        cimd_url=normalize_cimd_url(cimd_url),
        created_by=created_by,
        secure_value=hash_key_value(plaintext),
        mask_value=mask_key_value(plaintext),
    )
    return token, plaintext


class CIMDBlocklistEntry(models.Model):
    """Persistent blocklist for CIMD partner URLs.

    Source of truth for is_cimd_url_blocked - the Redis check is a read-through
    cache. Persisting in Postgres means the blocklist survives Redis flushes /
    LRU eviction and a deleted CIMD app can stay blocked across restarts.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    cimd_url: models.URLField = models.URLField(max_length=2048, unique=True)
    reason: models.CharField = models.CharField(max_length=200, blank=True, default="")
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    created_by: "User | None" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "CIMD Blocklist Entry"
        verbose_name_plural = "CIMD Blocklist Entries"


logger = structlog.get_logger(__name__)


@receiver(user_logged_out)
def _revoke_impersonation_oauth_tokens(sender, request, user, **kwargs):
    """Revoke OAuth tokens minted during an impersonation session when it ends.

    Fires on every logout, but only acts on impersonation logouts — when the loginas
    session flag is still set and we can recover the original (staff) user. Tokens
    are matched by `(user=<impersonated>, impersonated_by=<staff>)`, so only tokens
    this admin minted during this kind of impersonation are revoked; the customer's
    own pre-existing tokens (impersonated_by IS NULL) are untouched.

    Lives in the model module so the receiver is registered as soon as Django
    imports `OAuthAccessToken` — no explicit `apps.py` wiring required.
    """
    if request is None or user is None:
        return

    from posthog.helpers.impersonation import get_original_user_from_session, is_impersonated_session

    if not is_impersonated_session(request):
        return

    impersonator = get_original_user_from_session(request)
    if impersonator is None:
        return

    now = timezone.now()
    access_deleted, _ = OAuthAccessToken.objects.filter(user=user, impersonated_by=impersonator).delete()
    refresh_revoked = OAuthRefreshToken.objects.filter(
        user=user, impersonated_by=impersonator, revoked__isnull=True
    ).update(revoked=now)
    grants_deleted, _ = OAuthGrant.objects.filter(user=user, impersonated_by=impersonator).delete()

    if access_deleted or refresh_revoked or grants_deleted:
        logger.info(
            "impersonation_oauth_tokens_revoked",
            impersonated_user_id=user.pk,
            impersonator_user_id=impersonator.pk,
            access_tokens_deleted=access_deleted,
            refresh_tokens_revoked=refresh_revoked,
            grants_deleted=grants_deleted,
        )


@receiver(models.signals.post_delete, sender=OAuthApplication)
def _block_cimd_url_on_application_delete(sender, instance: OAuthApplication, **kwargs):
    # Auto-blocklist a CIMD URL when its app is deleted, so a metadata refresh
    # can't immediately recreate the same partner. Admin can explicitly
    # unblock via unblock_cimd_url if they want to allow re-registration.
    if not (instance.is_cimd_client and instance.cimd_metadata_url):
        return
    from posthog.api.oauth.cimd import block_cimd_url

    block_cimd_url(
        instance.cimd_metadata_url,
        reason=f"Auto-blocked on deletion of OAuthApplication {instance.pk}",
    )
