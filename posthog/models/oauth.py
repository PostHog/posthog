import enum
from typing import TYPE_CHECKING, cast
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.signals import user_logged_out
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.dispatch import receiver
from django.utils import timezone

import structlog
from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
)
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.validators import AllowedURIValidator

from posthog.helpers.encrypted_fields import EncryptedCharField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import UUIDT, generate_random_token, hash_key_value, mask_key_value

if TYPE_CHECKING:
    from posthog.models import Organization, User


class OAuthApplicationAccessLevel(enum.Enum):
    ALL = "all"
    ORGANIZATION = "organization"
    TEAM = "team"


class OAuthApplicationAuthBrand(enum.Enum):
    POSTHOG = "posthog"
    TWIG = "twig"


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

    # Provisioning fields - only relevant for partners that provision accounts/resources
    # via the agentic provisioning API. Null/blank for regular OAuth clients.
    provisioning_auth_method: models.CharField = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Auth method for provisioning requests: hmac, bearer, or pkce. Empty for non-provisioning apps.",
    )
    provisioning_signing_secret = EncryptedCharField(
        max_length=500,
        blank=True,
        null=True,
        default="",
        help_text="HMAC shared secret for provisioning request verification (encrypted at rest)",
    )
    provisioning_partner_type: models.CharField = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Partner identifier: stripe, wizard, etc. Empty for non-provisioning apps.",
    )
    provisioning_active: models.BooleanField = models.BooleanField(
        default=False, help_text="Must be explicitly enabled for provisioning access"
    )
    provisioning_can_create_accounts: models.BooleanField = models.BooleanField(
        default=False, help_text="Can this app create PostHog accounts on behalf of users"
    )
    provisioning_can_provision_resources: models.BooleanField = models.BooleanField(
        default=True, help_text="Can this app provision projects and API keys"
    )
    provisioning_issues_personal_api_key: models.BooleanField = models.BooleanField(
        default=False,
        db_default=False,
        help_text=(
            "Whether provisioning mints a Personal API Key for this app. Off by default; "
            "only grandfathered apps (the legacy Stripe app) still issue one, capped at the app's scopes."
        ),
    )
    provisioning_rate_limit_account_requests: models.IntegerField = models.IntegerField(
        null=True, blank=True, help_text="Override default rate limit for account_requests (per hour)"
    )
    provisioning_rate_limit_account_requests_source: models.CharField = models.CharField(
        max_length=24,
        blank=True,
        default="",
        choices=[
            ("default_unverified", "default_unverified"),
            ("default_verified", "default_verified"),
            ("admin", "admin"),
        ],
        help_text=(
            "Records who set provisioning_rate_limit_account_requests so verification flips don't "
            "overwrite an explicit admin override."
        ),
    )
    provisioning_rate_limit_token_exchanges: models.IntegerField = models.IntegerField(
        null=True, blank=True, help_text="Override default rate limit for token exchanges (per hour)"
    )
    provisioning_rate_limit_resource_creates: models.IntegerField = models.IntegerField(
        null=True, blank=True, help_text="Override default rate limit for resource creates (per hour)"
    )
    provisioning_rate_limit_github_grants: models.IntegerField = models.IntegerField(
        null=True, blank=True, help_text="Override default rate limit for GitHub grant creation (per hour)"
    )
    provisioning_disabled: models.BooleanField = models.BooleanField(
        default=False,
        help_text=(
            "Kill switch for misbehaving partners. When true, apply_provisioning_defaults will not "
            "re-enable the app on subsequent CIMD requests."
        ),
    )
    provisioning_skip_existing_user_consent: models.BooleanField = models.BooleanField(
        default=False,
        help_text="Skip user consent when linking existing accounts. Only enable for fully trusted partners.",
    )
    provisioning_can_issue_deep_links: models.BooleanField = models.BooleanField(
        default=False,
        help_text="Allow this app to issue deep links that mint full web sessions. Only enable for fully trusted partners.",
    )

    @property
    def is_provisioning_partner(self) -> bool:
        return bool(self.provisioning_auth_method)

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
        self._validate_application_config()

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


class OAuthAccessToken(AbstractAccessToken):
    class Meta(AbstractAccessToken.Meta):
        verbose_name = "OAuth Access Token"
        verbose_name_plural = "OAuth Access Tokens"
        swappable = "OAUTH2_PROVIDER_ACCESS_TOKEN_MODEL"
        indexes = [
            # The gateway credential cache scans for tokens holding a given scope via a
            # whitespace-bounded regex on the space-separated `scope` text. A trigram GIN
            # index lets that parameterized `~*` use an index scan; partial on
            # application_id IS NOT NULL (which every such scan already filters on) keeps
            # it to app tokens. See posthog/storage/gateway_credential_cache.py.
            GinIndex(
                fields=["scope"],
                name="oauthaccesstoken_scope_trgm",
                opclasses=["gin_trgm_ops"],
                condition=Q(application__isnull=False),
            ),
            # B-tree on the plaintext `token` so equality lookups by token value resolve
            # via an index scan instead of a sequential scan. These lookups account for a
            # large share of the server's CPU time; the index removes that hot-path scan.
            models.Index(fields=["token"], name="oauthaccesstoken_token_idx"),
        ]

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


def revoke_oauth_session(
    access_token: OAuthAccessToken | None = None, refresh_token: OAuthRefreshToken | None = None
) -> None:
    """Revoke all OAuth artifacts related to a session (access token, refresh token, and grant)."""
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
        # Delete all access tokens for this user+application
        OAuthAccessToken.objects.filter(user=user, application=application).delete()

        # Revoke all refresh tokens for this user+application
        OAuthRefreshToken.objects.filter(user=user, application=application, revoked__isnull=True).update(revoked=now)

        # Delete all grants for this user+application
        OAuthGrant.objects.filter(user=user, application=application).delete()


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


class CIMDVerificationToken(models.Model):
    """Token that links a CIMD partner app to a PostHog organization.

    A partner embeds the plaintext token in their CIMD metadata document under
    `posthog_verification_token`. On fetch, we hash and look up the token; if it
    matches, we link the resulting OAuthApplication to this organization and
    apply the verified-partner rate-limit tier.
    """

    id: models.UUIDField = models.UUIDField(primary_key=True, default=UUIDT, editable=False)
    organization: "Organization" = models.ForeignKey(  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        "posthog.Organization", on_delete=models.CASCADE, related_name="cimd_verification_tokens"
    )
    label: models.CharField = models.CharField(max_length=40)
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
    *, organization: "Organization", label: str, created_by: "User | None" = None
) -> tuple[CIMDVerificationToken, str]:
    """Create a new token, returning (instance, plaintext). Plaintext is only
    available at creation time — we only persist its hash."""
    plaintext = generate_random_token_cimd_verification()
    token = CIMDVerificationToken.objects.create(
        organization=organization,
        label=label,
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
