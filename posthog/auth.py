import re
import hmac
import time
import hashlib
import logging
import functools
from abc import abstractmethod
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional, TypedDict, Union
from urllib.parse import parse_qs, urlparse

from django.apps import apps
from django.conf import settings
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

import jwt
import structlog
from opentelemetry import trace
from prometheus_client import Counter
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from webauthn.helpers import base64url_to_bytes
from zxcvbn import zxcvbn

from posthog.clickhouse.query_tagging import AccessMethod, tag_authentication
from posthog.constants import AvailableFeature
from posthog.helpers.two_factor_session import enforce_two_factor
from posthog.internal_api_secret import usable_internal_api_secrets
from posthog.jwt import PosthogJwtAudience, decode_jwt, get_oidc_verification_keys
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthApplicationAuthBrand
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import (
    LEGACY_PERSONAL_API_KEY_SALT,
    PERSONAL_API_KEY_AUTH_COUNTER,
    PERSONAL_API_KEY_MODES_TO_TRY,
    PersonalAPIKey,
)
from posthog.models.project_secret_api_key import ProjectSecretAPIKey, find_project_secret_api_key
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from posthog.models.utils import hash_key_value
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.passkey import verify_passkey_authentication_response
from posthog.synthetic_user import SyntheticUser


class WebAuthnAuthenticationResponse(TypedDict):
    """WebAuthn authentication response data structure."""

    authenticatorData: str
    clientDataJSON: str
    signature: str
    userHandle: str


if TYPE_CHECKING:
    from posthog.models.share_password import SharePassword

logger = logging.getLogger(__name__)
structlog_logger = structlog.get_logger(__name__)

tracer = trace.get_tracer(__name__)

_SECRET_API_KEY_RE = re.compile(r"^phs_[a-zA-Z0-9]+$")

SECRET_API_KEY_BODY_FIELD = "secret_api_key"

SECRET_API_KEY_BODY_COUNTER = Counter(
    "api_auth_secret_api_key_body",
    "Requests where the team secret token is provided in the request body instead of the Authorization header",
)

PERSONAL_API_KEY_QUERY_PARAM_COUNTER = Counter(
    "api_auth_personal_api_key_query_param",
    "Requests where the personal api key is specified in a query parameter",
    labelnames=["user_uuid"],
)

AUTH_BRAND_COOKIE = "ph_auth_brand"


def get_auth_brand_for_client_id(client_id: str | None) -> str | None:
    if not client_id:
        return None
    try:
        application = OAuthApplication.objects.only("auth_brand", "is_first_party").get(client_id=client_id)
    except OAuthApplication.DoesNotExist:
        return None
    if not application.is_first_party:
        return None
    return application.auth_brand or None


def get_auth_brand_from_next_param(next_param: str | None) -> str | None:
    if not next_param:
        return None
    try:
        parsed = urlparse(next_param)
        client_id = parse_qs(parsed.query).get("client_id", [None])[0]
        return get_auth_brand_for_client_id(client_id)
    except (ValueError, IndexError, KeyError):
        return None


def normalize_auth_brand(value: str | None) -> str | None:
    if not value:
        return None
    allowed_brands = {brand.value for brand in OAuthApplicationAuthBrand}
    return value if value in allowed_brands else None


def apply_auth_brand_cookie(request: HttpRequest, response: JsonResponse | HttpResponse) -> JsonResponse | HttpResponse:
    brand = get_auth_brand_for_client_id(request.GET.get("client_id")) or get_auth_brand_from_next_param(
        request.GET.get("next")
    )
    brand = normalize_auth_brand(brand)
    if brand:
        response.set_cookie(
            key=AUTH_BRAND_COOKIE,
            value=brand,
            max_age=60 * 30,
            samesite="Lax",
            secure=request.is_secure(),
            httponly=True,
        )
    return response


class ZxcvbnValidator:
    """
    Validate that the password satisfies zxcvbn
    """

    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        result = zxcvbn(password)

        if result["score"] < 3:
            joined_feedback = " ".join(result["feedback"]["suggestions"])

            raise ValidationError(
                joined_feedback or "This password is too weak.",
                code="password_too_weak",
            )


class SessionAuthentication(authentication.SessionAuthentication):
    """
    This class is needed, because REST Framework's default SessionAuthentication does never return 401's,
    because they cannot fill the WWW-Authenticate header with a valid value in the 401 response. As a
    result, we cannot distinguish calls that are not unauthorized (401 unauthorized) and calls for which
    the user does not have permission (403 forbidden). See https://github.com/encode/django-rest-framework/issues/5968

    We do set authenticate_header function in SessionAuthentication, so that a value for the WWW-Authenticate
    header can be retrieved and the response code is automatically set to 401 in case of unauthenticated requests.

    This class is also used to enforce Two-Factor Authentication for session-based authentication.
    """

    def authenticate(self, request):
        with tracer.start_as_current_span("posthog.auth.session"):
            auth_result = super().authenticate(request)

            if not auth_result:
                return None

            user, auth = auth_result
            enforce_two_factor(request, user)

            return (user, auth)

    def authenticate_header(self, request):
        return "Session"


class PersonalAPIKeyAuthentication(authentication.BaseAuthentication):
    """A way of authenticating with personal API keys.
    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    3. Request query string.
    """

    keyword = "Bearer"
    personal_api_key: PersonalAPIKey
    personal_api_key_source: Optional[str] = None

    # Normalized source identifiers returned by find_key_with_source
    SOURCE_HEADER = "header"
    SOURCE_BODY = "body"
    SOURCE_QUERY_STRING = "query_string"

    _SOURCE_DISPLAY = {
        SOURCE_HEADER: "Authorization header",
        SOURCE_BODY: "body",
        SOURCE_QUERY_STRING: "query string",
    }

    message = "Invalid personal API key."

    @classmethod
    def find_key_with_source(
        cls,
        request: Union[HttpRequest, Request],
        request_data: Optional[dict[str, Any]] = None,
        extra_data: Optional[dict[str, Any]] = None,
    ) -> Optional[tuple[str, str]]:
        """Try to find personal API key in request and return it along with where it was found."""
        if "authorization" in request.headers:
            authorization_match = re.match(rf"^{cls.keyword}\s+(\S.+)$", request.headers["authorization"])
            if authorization_match:
                token = authorization_match.group(1).strip()

                if token.startswith(
                    "pha_"
                ):  # TRICKY: This returns None to allow the next authentication method to have a go. This should be `if not token.startswith("phx_")`, but we need to support legacy personal api keys that may not have been prefixed with phx_.
                    return None
                return token, cls.SOURCE_HEADER
        data = request.data if request_data is None and isinstance(request, Request) else request_data

        if data and "personal_api_key" in data:
            return data["personal_api_key"], cls.SOURCE_BODY
        if "personal_api_key" in request.GET:
            return request.GET["personal_api_key"], cls.SOURCE_QUERY_STRING
        return None

    @classmethod
    def find_key(
        cls,
        request: Union[HttpRequest, Request],
        request_data: Optional[dict[str, Any]] = None,
        extra_data: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """Try to find personal API key in request and return it."""
        key_with_source = cls.find_key_with_source(request, request_data, extra_data)
        return key_with_source[0] if key_with_source is not None else None

    @classmethod
    @transaction.atomic
    def validate_key(cls, personal_api_key_with_source):
        from posthog.models import PersonalAPIKey

        personal_api_key, source = personal_api_key_with_source
        personal_api_key_object = None
        mode_used = None
        modes_tried = 0

        with tracer.start_as_current_span("posthog.auth.personal_api_key.db_lookup") as db_span:
            for mode, iterations in PERSONAL_API_KEY_MODES_TO_TRY:
                modes_tried += 1
                secure_value = hash_key_value(
                    personal_api_key, mode=mode, legacy_salt=LEGACY_PERSONAL_API_KEY_SALT, iterations=iterations
                )
                try:
                    personal_api_key_object = (
                        PersonalAPIKey.objects.select_related("user")
                        .filter(user__is_active=True)
                        .get(secure_value=secure_value)
                    )
                    mode_used = mode
                    PERSONAL_API_KEY_AUTH_COUNTER.labels(hash_mode=mode).inc()
                    break
                except PersonalAPIKey.DoesNotExist:
                    pass

            db_span.set_attribute("auth.modes_tried", modes_tried)
            if mode_used:
                db_span.set_attribute("auth.hash_mode_used", mode_used)

        if not personal_api_key_object:
            source_display = cls._SOURCE_DISPLAY.get(source, source)
            raise AuthenticationFailed(detail=f"Personal API key found in request {source_display} is invalid.")

        # Upgrade the key if it's not in the latest mode. We can do this since above we've already checked
        # that the key is valid in some mode, and we do check for all modes one by one.
        if mode_used != "sha256":
            with tracer.start_as_current_span("posthog.auth.personal_api_key.mode_upgrade") as upgrade_span:
                upgrade_span.set_attribute("auth.hash_mode_used", mode_used or "")
                key_to_update = PersonalAPIKey.objects.select_for_update().get(id=personal_api_key_object.id)
                key_to_update.secure_value = hash_key_value(personal_api_key)
                key_to_update.save(update_fields=["secure_value"])

        if source == cls.SOURCE_QUERY_STRING:
            PERSONAL_API_KEY_QUERY_PARAM_COUNTER.labels(personal_api_key_object.user.uuid).inc()

        return personal_api_key_object

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        with tracer.start_as_current_span("posthog.auth.personal_api_key") as span:
            personal_api_key_with_source = self.find_key_with_source(request)
            if not personal_api_key_with_source:
                return None

            _, source = personal_api_key_with_source
            span.set_attribute("auth.source", source)

            personal_api_key_object = self.validate_key(personal_api_key_with_source)

            now = timezone.now()
            key_last_used_at = personal_api_key_object.last_used_at
            # Only updating last_used_at if the hour's changed
            # This is to avoid excessive UPDATE queries, while still presenting accurate (down to the hour) info in the UI
            if key_last_used_at is None or (now - key_last_used_at > timedelta(hours=1)):
                personal_api_key_object.last_used_at = now
                personal_api_key_object.save(update_fields=["last_used_at"])
            assert personal_api_key_object.user is not None

            # :KLUDGE: CHMiddleware does not receive the correct user when authenticating by api key.
            tag_authentication(
                user_id=personal_api_key_object.user.pk,
                team_id=personal_api_key_object.user.current_team_id,
                access_method=AccessMethod.PERSONAL_API_KEY,
                api_key_mask=personal_api_key_object.mask_value,
                api_key_label=personal_api_key_object.label,
            )

            self.personal_api_key = personal_api_key_object
            self.personal_api_key_source = source

            return personal_api_key_object.user, None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


def _extract_phs_token(request: Union[HttpRequest, Request], allow_body_token: bool = False) -> Optional[str]:
    """
    Find a `phs_` secret token in the request. Checks the Authorization header first
    (Bearer scheme), then the request body field `secret_api_key`. Used by both
    TeamSecretTokenAuthentication (legacy Team.secret_api_token) and
    ProjectSecretAPIKeyAuthentication (PSAK model).
    """
    if "authorization" in request.headers:
        authorization_match = re.match(r"^Bearer\s+(.+)$", request.headers["authorization"])
        if authorization_match:
            token = authorization_match.group(1).strip()
            if _SECRET_API_KEY_RE.match(token):
                return token

    if allow_body_token:
        # Wrap HttpRequest in a DRF Request only when we actually need to read the parsed body.
        if not isinstance(request, Request):
            request = Request(request)
        data = request.data
        if isinstance(data, dict):
            candidate = data.get(SECRET_API_KEY_BODY_FIELD)
            if isinstance(candidate, str) and _SECRET_API_KEY_RE.match(candidate):
                SECRET_API_KEY_BODY_COUNTER.inc()
                return candidate

    return None


class TeamSecretTokenUser(SyntheticUser):
    """
    Synthetic user returned by TeamSecretTokenAuthentication when authenticating
    via the legacy team-level Team.secret_api_token field.
    """

    def __init__(self, team):
        super().__init__(team, distinct_id=f"team-secret-token-{team.id}")


class TeamSecretTokenAuthentication(authentication.BaseAuthentication):
    """
    Authenticates using the legacy team-level Team.secret_api_token field.

    This is not a ProjectSecretAPIKey (PSAK) model authenticator — it validates the
    `phs_*` token against the legacy per-team secret stored on the Team row. It's
    intended for endpoints that were gated before PSAK existed.

    When authenticated, returns a synthetic TeamSecretTokenUser with the team
    attached, so downstream permission code can resolve team context without a
    real User.

    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body (`secret_api_key` field).
    """

    keyword = "Bearer"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        secret_api_token = _extract_phs_token(request, allow_body_token=True)

        if not secret_api_token:
            return None

        try:
            Team = apps.get_model(app_label="posthog", model_name="Team")
            team = Team.objects.get_team_from_cache_or_secret_api_token(secret_api_token)

            if team is None:
                return None

            tag_authentication(
                user_id=None,
                team_id=team.id,
                access_method=AccessMethod.TEAM_SECRET_TOKEN,
            )

            return (TeamSecretTokenUser(team), None)
        except Team.DoesNotExist:
            return None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class ProjectSecretAPIKeyUser(SyntheticUser):
    """
    Synthetic user returned by ProjectSecretAPIKeyAuthentication. Carries the
    backing ProjectSecretAPIKey so APIScopePermission can read its scopes.
    """

    def __init__(self, project_secret_api_key):
        super().__init__(
            project_secret_api_key.team,
            distinct_id=f"psak-{project_secret_api_key.team_id}-{project_secret_api_key.id}",
        )
        self.project_secret_api_key = project_secret_api_key

    def readable_system_table_access_scopes(self) -> set[str]:
        return {scope.split(":", 1)[0] for scope in self.project_secret_api_key.scopes or [] if ":" in scope}


class ProjectSecretAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticates a ProjectSecretAPIKey (PSAK) model record via its SHA256 hash.

    Does NOT fall back to Team.secret_api_token — that's TeamSecretTokenAuthentication.
    Intended for endpoints that enforce PSAK scopes via APIScopePermission.

    PSAK scopes grant project-wide access within the scoped resource type. They do
    not honor object-level access controls like per-resource RBAC restrictions.
    """

    keyword = "Bearer"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        token = _extract_phs_token(request, allow_body_token=False)
        if not token:
            return None

        psak = find_project_secret_api_key(token)
        if psak is None:
            return None

        now = timezone.now()
        if psak.last_used_at is None or (now - psak.last_used_at > timedelta(hours=1)):
            # Use .update() to bypass ModelActivityMixin save hooks and avoid
            # activity-log noise / Redis cache invalidation on every request.
            ProjectSecretAPIKey.objects.filter(pk=psak.pk).update(last_used_at=now)

        self.project_secret_api_key = psak

        tag_authentication(
            user_id=None,
            team_id=psak.team_id,
            access_method=AccessMethod.PROJECT_SECRET_API_KEY,
            api_key_mask=psak.mask_value,
            api_key_label=psak.label,
        )

        return (ProjectSecretAPIKeyUser(psak), None)

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class JwtAuthentication(authentication.BaseAuthentication):
    """
    A way of authenticating with a JWT, primarily by background jobs impersonating a User
    """

    keyword = "Bearer"

    @classmethod
    def authenticate(cls, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        with tracer.start_as_current_span("posthog.auth.jwt"):
            if "authorization" in request.headers:
                authorization_match = re.match(rf"^Bearer\s+(\S.+)$", request.headers["authorization"])
                if authorization_match:
                    try:
                        token = authorization_match.group(1).strip()
                        info = decode_jwt(token, PosthogJwtAudience.IMPERSONATED_USER)
                        user = User.objects.get(pk=info["id"])
                        return (user, None)
                    except jwt.DecodeError:
                        # If it doesn't look like a JWT then we allow the PersonalAPIKeyAuthentication to have a go
                        return None
                    except Exception:
                        raise AuthenticationFailed(detail=f"Token invalid.")
                else:
                    # We don't throw so that the PersonalAPIKeyAuthentication can have a go
                    return None

            return None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class IDJagAccessTokenAuthentication(authentication.BaseAuthentication):
    """
    Authenticates inbound API requests using an access token minted by the
    ID-JAG (XAA) JWT Bearer grant served from the OAuth token endpoint
    (`/oauth/token`, logic in `posthog.api.id_jag`). Validates the JWT against the
    RS256 public key derived from `OIDC_RSA_PRIVATE_KEY` and binds the request
    to the User whose email matches the `userSub` half of the token's `sub`
    claim (`{provider}:{userSub}` per
    https://xaa.dev/docs/token-structure#sub-claim-format).

    Scope enforcement lives in `posthog.permissions.APIScopePermission`; this
    class only handles signature + claim validation and user resolution.
    """

    _ID_JAG_ACCESS_TOKEN_TYPE = "at+jwt"

    keyword = "Bearer"

    id_jag_claims: dict[str, Any]
    scopes: list[str]
    organization_id: str

    @classmethod
    def _extract_token(cls, request: Union[HttpRequest, Request]) -> Optional[str]:
        auth_header = request.headers.get("authorization")
        if not auth_header:
            return None
        match = re.match(rf"^{cls.keyword}\s+(\S.+)$", auth_header)
        if not match:
            return None
        token = match.group(1).strip()

        return token

    @classmethod
    def _parse_sub(cls, sub: str) -> Optional[tuple[str, str]]:
        """`{providerName}:{userSub}` per spec — split into (provider, user_sub).

        Returns None if the format is malformed (no colon, empty provider, empty
        user_sub) so the caller can fail with `invalid_token`.
        """
        if not sub or ":" not in sub:
            return None
        provider, user_sub = sub.split(":", 1)
        if not provider or not user_sub:
            return None
        return provider, user_sub

    @classmethod
    def _is_id_jag_token(cls, token: str) -> bool:
        # Personal/OAuth API key prefixes are reserved for those auth backends.
        if token.startswith(("phx_", "pha_", "phs_")):
            return False

        if token.count(".") != 2:
            return False
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            return False
        return header.get("typ") == cls._ID_JAG_ACCESS_TOKEN_TYPE

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        with tracer.start_as_current_span("posthog.auth.id_jag"):
            token = self._extract_token(request)
            if not token:
                return None
            if not self._is_id_jag_token(token):
                return None

            verification_keys = get_oidc_verification_keys()
            if not verification_keys:
                raise AuthenticationFailed(detail="ID-JAG access tokens are not configured on this server.")

            site_url = (settings.SITE_URL or "").rstrip("/")
            if not site_url:
                raise AuthenticationFailed(detail="ID-JAG access tokens are not configured on this server.")

            # The token's `aud` is the resource it was minted for (id_jag._construct_access_token_payload).
            # Accept SITE_URL plus any advertised resource identifier; `iss` stays SITE_URL (we mint it).
            # Function-level import keeps the heavier id_jag module off auth.py's foundational import path.
            from posthog.api.id_jag import get_allowed_resources  # noqa: PLC0415

            allowed_resources = get_allowed_resources()

            # Try the active signing key first, then any keys being rotated out. A wrong
            # key fails the signature check, so we move on; a key that matches but fails
            # claim validation (expiry, audience, …) raises the real error to report.
            claims = None
            for verification_key in verification_keys:
                try:
                    claims = jwt.decode(
                        token,
                        verification_key,
                        algorithms=["RS256"],
                        audience=allowed_resources,
                        issuer=site_url,
                        leeway=settings.ID_JAG_CLOCK_SKEW_SECONDS,
                        options={
                            "require": ["iss", "sub", "email", "aud", "exp", "iat", "client_id", "scope", "org_id"],
                            "verify_signature": True,
                            "verify_exp": True,
                            "verify_aud": True,
                            "verify_iss": True,
                        },
                    )
                    break
                except jwt.InvalidSignatureError:
                    continue
                except jwt.ExpiredSignatureError:
                    raise AuthenticationFailed(detail="ID-JAG access token has expired.")
                except jwt.InvalidAudienceError:
                    raise AuthenticationFailed(
                        detail="ID-JAG access token audience does not match this resource server."
                    )
                except jwt.InvalidIssuerError:
                    raise AuthenticationFailed(detail="ID-JAG access token has an unexpected issuer.")
                except jwt.MissingRequiredClaimError as e:
                    raise AuthenticationFailed(detail=f"ID-JAG access token is missing required claim: {e.claim}.")
                except jwt.PyJWTError:
                    raise AuthenticationFailed(detail="ID-JAG access token is invalid.")

            if claims is None:
                raise AuthenticationFailed(detail="ID-JAG access token is invalid.")

            sub_parts = self._parse_sub(str(claims.get("sub", "")))
            if sub_parts is None:
                raise AuthenticationFailed(
                    detail="ID-JAG access token sub claim is not in the expected '{provider}:{userSub}' format."
                )

            organization_id = str(claims.get("org_id") or "")
            if not organization_id:
                raise AuthenticationFailed(detail="ID-JAG access token is missing the org_id claim.")

            token_email = str(claims.get("email") or "")
            if not token_email:
                raise AuthenticationFailed(detail="ID-JAG access token is missing the email claim.")

            # Resolve the user by (email, org_id) so the token only authenticates
            # against the specific organization it was minted for. This prevents
            # a token from authenticating as another user that happens to share
            # the email, and re-validates membership at every request (the user
            # may have been removed from the org after the token was issued).
            membership = (
                OrganizationMembership.objects.filter(
                    organization_id=organization_id,
                    user__is_active=True,
                    user__email__iexact=token_email,
                )
                .select_related("user", "organization")
                .first()
            )
            if not membership:
                raise AuthenticationFailed(
                    detail="No active PostHog user matches the ID-JAG access token subject for this organization."
                )

            user = membership.user
            organization = membership.organization

            if not organization.is_feature_available(AvailableFeature.XAA_AUTHENTICATION):
                raise AuthenticationFailed(detail="ID-JAG (XAA) is not enabled for this organization.")

            self.id_jag_claims = claims
            self.scopes = str(claims.get("scope") or "").split()
            self.organization_id = organization_id

            tag_authentication(
                user_id=user.pk,
                team_id=user.current_team_id,
                access_method=AccessMethod.ID_JAG,
            )

            return user, None

    def authenticate_header(self, request) -> str:
        return self.keyword


class ExportRendererAuthentication(authentication.BaseAuthentication):
    """
    Scoped JWT auth for the export renderer. Only accepted on viewsets that opt in.
    """

    keyword = "Bearer"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        if request.method not in ("GET", "HEAD"):
            return None
        if "authorization" not in request.headers:
            return None
        authorization_match = re.match(rf"^Bearer\s+(\S.+)$", request.headers["authorization"])
        if not authorization_match:
            return None
        try:
            token = authorization_match.group(1).strip()
            info = decode_jwt(token, PosthogJwtAudience.EXPORT_RENDERER)
            user = User.objects.get(pk=info["id"])
            return user, None
        except (jwt.DecodeError, jwt.InvalidAudienceError):
            return None
        except Exception:
            raise AuthenticationFailed(detail="Token invalid.")

    def authenticate_header(self, request) -> str:
        return self.keyword


def _organization_disallows_public_sharing(sharing_configuration: SharingConfiguration) -> bool:
    """Returns True when the organization has disabled public sharing under the
    ORGANIZATION_SECURITY_SETTINGS feature. Sharing tokens must fail closed in that case,
    even though individual `SharingConfiguration` rows remain `enabled=True`.
    """
    # Fetch the organization directly via the team FK rather than `sharing_configuration.team.organization`,
    # which would lazy-load the entire wide `posthog_team` row just to hop to the organization.
    organization = Organization.objects.get(team=sharing_configuration.team_id)
    return (
        organization.is_feature_available(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)
        and not organization.allow_publicly_shared_resources
    )


class SharingAccessTokenAuthentication(authentication.BaseAuthentication):
    """Limited access for sharing views e.g. insights/dashboards for refreshing.
    Remember to add access restrictions based on `sharing_configuration` using `SharingTokenPermission` or manually.
    """

    sharing_configuration: SharingConfiguration

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, Any]]:
        if sharing_access_token := request.GET.get("sharing_access_token"):
            if request.method not in ["GET", "HEAD"]:
                raise AuthenticationFailed(detail="Sharing access token can only be used for GET requests.")
            try:
                sharing_configuration = (
                    SharingConfiguration.objects.select_related(
                        # Preload the artifact creator, resolved on every token-authenticated request
                        "insight__created_by",
                        "dashboard__created_by",
                        "notebook__created_by",
                    )
                    .filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=timezone.now()))
                    .get(access_token=sharing_access_token, enabled=True)
                )

                # If password is required, don't authenticate via direct access_token
                # Let the view handle showing the unlock page
                if sharing_configuration.password_required:
                    return None

            except SharingConfiguration.DoesNotExist:
                raise AuthenticationFailed(detail="Sharing access token is invalid.")
            else:
                if _organization_disallows_public_sharing(sharing_configuration):
                    raise AuthenticationFailed(detail="Sharing access token is invalid.")

                self.sharing_configuration = sharing_configuration
                return (AnonymousUser(), None)
        return None


class SharingPasswordProtectedAuthentication(authentication.BaseAuthentication):
    """
    JWT-based authentication for password-protected shared resources.
    Supports both Bearer token (for API calls) and cookie (for rendering decisions).
    """

    keyword = "Bearer"
    sharing_configuration: SharingConfiguration
    share_password: "SharePassword"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, Any]]:
        if request.method != "GET":
            return None

        # Extract JWT token from Authorization header or cookie
        sharing_jwt_token = None
        if "authorization" in request.headers:
            authorization_match = re.match(rf"^{self.keyword}\s+(\S.+)$", request.headers["authorization"])
            if authorization_match:
                sharing_jwt_token = authorization_match.group(1).strip()
        elif hasattr(request, "COOKIES") and request.COOKIES.get("posthog_sharing_token"):
            sharing_jwt_token = request.COOKIES.get("posthog_sharing_token")

        if not sharing_jwt_token:
            return None

        try:
            # Attempt full JWT validation - this will fail fast for non-sharing JWTs due to audience mismatch
            payload = decode_jwt(sharing_jwt_token, PosthogJwtAudience.SHARING_PASSWORD_PROTECTED)

            from posthog.models.share_password import SharePassword

            share_password = (
                SharePassword.objects.select_related("sharing_configuration")
                .filter(
                    models.Q(sharing_configuration__expires_at__isnull=True)
                    | models.Q(sharing_configuration__expires_at__gt=timezone.now())
                )
                .get(
                    id=payload["share_password_id"],
                    sharing_configuration__team_id=payload["team_id"],
                    sharing_configuration__enabled=True,
                    sharing_configuration__password_required=True,
                    is_active=True,
                )
            )

            sharing_configuration = share_password.sharing_configuration

            # Verify the access token matches (prevents token reuse across different shares)
            if sharing_configuration.access_token != payload.get("access_token"):
                return None

            if _organization_disallows_public_sharing(sharing_configuration):
                raise AuthenticationFailed(detail="Sharing access token is invalid.")

            self.sharing_configuration = sharing_configuration
            self.share_password = share_password
            return (AnonymousUser(), None)

        except jwt.InvalidTokenError:
            # Expected: JWT decode failed (likely a personal API key was passed)
            # Let the next authenticator (PersonalAPIKeyAuthentication) handle it
            return None
        except AuthenticationFailed:
            # Intentional auth failures (e.g. organization kill switch) must propagate,
            # not be swallowed by the generic Exception handler below.
            raise
        except Exception as e:
            # Unexpected: Database issues, programming errors, etc.
            # Log for debugging but still fail gracefully
            logger.info(
                "SharingPasswordProtectedAuthentication failed with unexpected exception",
                exc_info=True,
                extra={"exception_type": type(e).__name__, "exception_message": str(e)},
            )
            return None


class OAuthAccessTokenAuthentication(authentication.BaseAuthentication):
    """
    OAuth 2.0 Bearer token authentication using access tokens
    """

    keyword = "Bearer"
    access_token: OAuthAccessToken

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        with tracer.start_as_current_span("posthog.auth.oauth"):
            authorization_token = self._extract_token(request)

            if not authorization_token:
                return None

            try:
                access_token = self._validate_token(authorization_token)

                if not access_token:
                    raise AuthenticationFailed(detail="Invalid access token.")

                self.access_token = access_token

                tag_authentication(
                    user_id=access_token.user.pk,
                    team_id=access_token.user.current_team_id,
                    access_method=AccessMethod.OAUTH,
                )

                return access_token.user, None

            except AuthenticationFailed:
                raise
            except Exception:
                raise AuthenticationFailed(detail="Invalid access token.")

    def _extract_token(self, request: Union[HttpRequest, Request]) -> Optional[str]:
        if "authorization" in request.headers:
            authorization_match = re.match(rf"^{self.keyword}\s+(\S.+)$", request.headers["authorization"])
            if authorization_match:
                token = authorization_match.group(1).strip()

                if token.startswith("pha_"):
                    return token
                return None
        return None

    def _validate_token(self, token: str):
        try:
            access_token = OAuthAccessToken.objects.select_related("user").get(token=token)

            if access_token.is_expired():
                raise AuthenticationFailed(detail="Access token has expired.")

            if not access_token.user:
                raise AuthenticationFailed(detail="User associated with access token not found.")

            if not access_token.user.is_active:
                raise AuthenticationFailed(detail="User associated with access token is disabled.")

            if not access_token.application_id:
                raise AuthenticationFailed(detail="Access token is not associated with a valid application.")

            return access_token

        except OAuthAccessToken.DoesNotExist:
            return None
        except AuthenticationFailed:
            raise
        except Exception:
            raise AuthenticationFailed(detail="Failed to validate access token.")

    def authenticate_header(self, request):
        return self.keyword


class WidgetAuthentication(authentication.BaseAuthentication):
    """
    Authenticate widget requests via conversations_settings.widget_public_token.
    This provides team-level authentication only. User-level scoping
    is enforced via widget_session_id validation in each endpoint.
    """

    def authenticate(self, request: Request) -> Optional[tuple[None, Any]]:
        """
        Returns (None, team) on success.
        No user object since this is public widget auth.
        """
        token = request.headers.get("X-Conversations-Token")
        if not token:
            return None  # Let other authenticators try

        try:
            Team = apps.get_model(app_label="posthog", model_name="Team")
            team = Team.objects.get(conversations_settings__widget_public_token=token, conversations_enabled=True)
        except Team.DoesNotExist:
            raise AuthenticationFailed("Invalid token or conversations not enabled")

        return (None, team)


class InternalAPIUser:
    """Synthetic user for internal API authentication."""

    is_authenticated = True
    is_anonymous = False
    is_active = True
    pk = -2

    def __init__(self, current_organization_id: Any = None, current_team_id: int | None = None) -> None:
        self.current_organization_id = current_organization_id
        self.current_team_id = current_team_id

    def has_perm(self, perm, obj=None):
        return False

    def has_module_perms(self, app_label):
        return False


class InternalAPIAuthentication(authentication.BaseAuthentication):
    """DRF authentication backend for internal API calls."""

    keyword = "InternalApiSecret"
    HEADER_NAME = "X-Internal-Api-Secret"

    def _get_team_id_from_request(self, request: Request) -> str | None:
        parser_context = getattr(request, "parser_context", None)
        if isinstance(parser_context, dict):
            kwargs = parser_context.get("kwargs")
            if isinstance(kwargs, dict):
                team_id = kwargs.get("team_id")
                if team_id is not None:
                    return str(team_id)

        django_request = getattr(request, "_request", request)
        resolver_match = getattr(django_request, "resolver_match", None)
        if resolver_match and getattr(resolver_match, "kwargs", None):
            team_id = resolver_match.kwargs.get("team_id")
            if team_id is not None:
                return str(team_id)

        return None

    def _get_internal_api_user(self, request: Request) -> InternalAPIUser:
        team_id = self._get_team_id_from_request(request)
        if not team_id:
            return InternalAPIUser()

        Team = apps.get_model(app_label="posthog", model_name="Team")
        try:
            team = Team.objects.only("id", "organization_id").get(id=team_id)
        except (Team.DoesNotExist, ValueError):
            raise AuthenticationFailed("Invalid internal API team.")

        return InternalAPIUser(current_organization_id=team.organization_id, current_team_id=team.id)

    def authenticate(self, request: Request) -> tuple[Any, Any]:
        provided_secret = (
            request.headers.get(self.HEADER_NAME)
            or request.headers.get(self.HEADER_NAME.lower())
            or request.headers.get(self.HEADER_NAME.upper())
        )
        # Trim the inbound header (e.g. a trailing newline from a mounted secret) so it can't cause
        # a spurious mismatch. The configured secrets are normalized at load (see data_stores.py).
        if provided_secret:
            provided_secret = provided_secret.strip()

        # Primary secret plus any still-trusted fallbacks (zero-downtime rotation), dropping empties.
        # This is the runtime guard: a deploy with no usable secret is rejected here (fail closed)
        # rather than at startup — most Django/Temporal processes never get the secret injected and
        # never serve these endpoints, so a startup check would wrongly crash them.
        accepted_secrets = usable_internal_api_secrets()

        if not accepted_secrets:
            logger.error(
                "Internal API authentication attempted without configured secret",
                extra={"path": request.path, "method": request.method},
            )
            raise AuthenticationFailed("Internal API authentication is not configured.")

        if not provided_secret:
            logger.warning(
                "Internal API request missing authentication header",
                extra={"path": request.path, "method": request.method},
            )
            raise AuthenticationFailed("Missing internal API authentication header.")

        if not any(hmac.compare_digest(secret, provided_secret) for secret in accepted_secrets):
            logger.warning(
                "Internal API request with invalid secret",
                extra={"path": request.path, "method": request.method},
            )
            raise AuthenticationFailed("Invalid internal API authentication.")

        return (self._get_internal_api_user(request), None)

    def authenticate_header(self, request: HttpRequest) -> str:
        return self.keyword


def session_auth_required(endpoint):
    """
    DEPRECATED: Require session authentication for function-based views.

    Returns 401 if user is not authenticated via session.
    """

    @functools.wraps(endpoint)
    def wrapper(request: HttpRequest):
        if not request.user.is_authenticated:
            return JsonResponse(
                {"detail": "Authentication credentials were not provided."},
                status=401,
            )
        return endpoint(request)

    return wrapper


class WebauthnBackend(BaseBackend):
    """
    Custom authentication backend for WebAuthn/passkey login.

    Handles the complete WebAuthn authentication flow:
    1. Extracts challenge from session
    2. Extracts userHandle and credential_id from request data
    3. Looks up user and credential
    4. Verifies the authentication response
    5. Updates credential sign count
    """

    name = "webauthn"

    def authenticate(
        self,
        request: Optional[Union[HttpRequest, Request]],
        credential_id: Optional[str] = None,
        challenge: Optional[str] = None,
        response: Optional[WebAuthnAuthenticationResponse] = None,
        **kwargs: Any,
    ) -> Optional[User]:
        """
        Authenticate a user via WebAuthn.

        Verifies the WebAuthn assertion and returns the authenticated user.

        Args:
            request: The HTTP request object
            credential_id: The base64url-encoded credential ID (rawId)
            challenge: The base64url-encoded challenge
            response: The WebAuthn authentication response containing userHandle, authenticatorData, clientDataJSON, and signature
        """
        if challenge is None or credential_id is None or response is None:
            structlog_logger.warning(
                "no request, response, or credential id while authenticating webauthn credential",
                credential_id=credential_id,
                challenge=challenge,
                response=response,
            )
            return None

        try:
            # Decode credential ID
            credential_id_bytes = base64url_to_bytes(credential_id)

            # Find the credential
            credential = (
                WebauthnCredential.objects.filter(credential_id=credential_id_bytes, verified=True)
                .select_related("user")
                .first()
            )

            if not credential:
                structlog_logger.warning("webauthn_login_credential_not_found", credential_id=credential_id)
                return None

            user = credential.user
            # Check if user is active
            if not user.is_active:
                structlog_logger.warning("webauthn_login_user_inactive", user_id=user.pk)
                return None

            # Construct credential dict for webauthn library
            # The library expects both 'id' and 'rawId' to be present
            credential_dict = {
                "id": credential_id,
                "rawId": credential_id,
                "response": response,
                "type": "public-key",
            }

            # Verify the authentication response
            expected_challenge = base64url_to_bytes(challenge)
            verification = verify_passkey_authentication_response(
                credential=credential_dict,
                expected_challenge=expected_challenge,
                credential_public_key=credential.public_key,
                credential_current_sign_count=credential.counter,
            )

            # Update sign count
            credential.counter = verification.new_sign_count
            credential.save()

            structlog_logger.info("webauthn_login_success", user_id=user.pk, credential_id=credential.pk)

            return user

        except Exception as e:
            structlog_logger.exception("webauthn_login_error", error=str(e))
            return None

    def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by their primary key.

        Required by Django's authentication system to load the user on subsequent requests.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class WebhookSignatureAuthentication(authentication.BaseAuthentication):
    """
    Base HMAC-SHA256 webhook signature authentication.

    Subclass and implement the abstract methods to support a specific provider.
    On success, sets request.auth to whatever `get_auth_context` returns.

    Typical provider differences:
      - Customer.io: signature header "X-Cio-Signature", input format "v0:{ts}:{body}"
      - Stripe:      signature header "Stripe-Signature",  input format "{ts}.{body}"
    """

    timestamp_tolerance: int = 300  # seconds

    @abstractmethod
    def get_signature_header(self) -> str:
        """Return the HTTP header name containing the HMAC signature."""
        ...

    @abstractmethod
    def get_timestamp_header(self) -> str:
        """Return the HTTP header name containing the request timestamp."""
        ...

    @abstractmethod
    def build_hmac_input(self, timestamp: str, body: str) -> str:
        """Build the string that was signed. Provider-specific format."""
        ...

    @abstractmethod
    def get_signing_secret(self, request: Request) -> str | None:
        """
        Look up the signing secret for this request.
        Return None if the webhook integration doesn't exist or is disabled.
        """
        ...

    def get_auth_context(self, request: Request) -> Any:
        """
        Return the object to set as ``request.auth`` after successful verification.
        Override to return an Integration, team, or other context.
        Defaults to the team_id from URL kwargs.
        """
        return self._get_team_id(request)

    def _get_team_id(self, request: Request) -> int | None:
        """Extract team_id from URL kwargs (works for both DRF and Django requests)."""
        django_request = getattr(request, "_request", request)
        resolver_match = getattr(django_request, "resolver_match", None)
        if resolver_match and resolver_match.kwargs:
            tid = resolver_match.kwargs.get("team_id")
            if tid is not None:
                return int(tid)
        return None

    def authenticate(self, request: Request) -> tuple[AnonymousUser, Any] | None:
        signature = request.headers.get(self.get_signature_header())
        timestamp = request.headers.get(self.get_timestamp_header())
        if not signature or not timestamp:
            raise AuthenticationFailed("Missing webhook signature headers.")

        signing_secret = self.get_signing_secret(request)
        if not signing_secret:
            raise AuthenticationFailed("Webhook integration not found or disabled.")

        django_request = getattr(request, "_request", request)
        raw_body = django_request.body.decode()

        hmac_input = self.build_hmac_input(timestamp, raw_body)
        expected = hmac.new(
            signing_secret.encode(),
            hmac_input.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationFailed("Invalid webhook signature.")

        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            raise AuthenticationFailed("Invalid webhook timestamp.")
        if abs(time.time() - ts) > self.timestamp_tolerance:
            raise AuthenticationFailed("Webhook timestamp too old.")

        # Return AnonymousUser (not None) so DRF throttles can safely access request.user.is_authenticated.
        return (AnonymousUser(), self.get_auth_context(request))

    def authenticate_header(self, request: Request) -> str:
        return "WebhookSignature"
