import re
import logging
import functools
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional, TypedDict, Union
from urllib.parse import parse_qs, urlparse, urlsplit

from django.apps import apps
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

import jwt
import structlog
from prometheus_client import Counter
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from webauthn.helpers import base64url_to_bytes
from zxcvbn import zxcvbn

from posthog.clickhouse.query_tagging import AccessMethod, tag_queries
from posthog.helpers.two_factor_session import enforce_two_factor
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models.oauth import OAuthAccessToken, OAuthApplication, OAuthApplicationAuthBrand
from posthog.models.personal_api_key import PERSONAL_API_KEY_MODES_TO_TRY, PersonalAPIKey, hash_key_value
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from posthog.models.webauthn_credential import WebauthnCredential
from posthog.passkey import verify_passkey_authentication_response


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
        # Only catch expected parsing errors
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
        auth_result = super().authenticate(request)

        if not auth_result:
            return None

        user, auth = auth_result
        enforce_two_factor(request, user)

        return (user, auth)

    def authenticate_header(self, request):
        return "Session"


class APIKeyAuthentication:
    def update_key_last_used_at(self, key_instance):
        now = timezone.now()
        key_last_used_at = key_instance.last_used_at
        # Only updating last_used_at if the hour's changed
        # This is to avoid excessive UPDATE queries, while still presenting accurate (down to the hour) info in the UI
        if key_last_used_at is None or (now - key_last_used_at > timedelta(hours=1)):
            type(key_instance).objects.filter(pk=key_instance.pk).update(last_used_at=now)


class PersonalAPIKeyAuthentication(authentication.BaseAuthentication, APIKeyAuthentication):
    """A way of authenticating with personal API keys.
    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    3. Request query string.
    """

    keyword = "Bearer"
    personal_api_key: PersonalAPIKey

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

                if (
                    token.startswith("pha_") or token.startswith("phs_")
                ):  # TRICKY: This returns None to allow the next authentication method to have a go. This should be `if not token.startswith("phx_")`, but we need to support legacy personal api keys that may not have been prefixed with phx_.
                    return None

                return token, "Authorization header"
        data = request.data if request_data is None and isinstance(request, Request) else request_data

        if data and "personal_api_key" in data:
            return data["personal_api_key"], "body"
        if "personal_api_key" in request.GET:
            return request.GET["personal_api_key"], "query string"
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

        for mode, iterations in PERSONAL_API_KEY_MODES_TO_TRY:
            secure_value = hash_key_value(personal_api_key, mode=mode, iterations=iterations)
            try:
                personal_api_key_object = (
                    PersonalAPIKey.objects.select_related("user")
                    .filter(user__is_active=True)
                    .get(secure_value=secure_value)
                )
                mode_used = mode
                break
            except PersonalAPIKey.DoesNotExist:
                pass

        if not personal_api_key_object:
            raise AuthenticationFailed(detail=f"Personal API key found in request {source} is invalid.")

        # Upgrade the key if it's not in the latest mode. We can do this since above we've already checked
        # that the key is valid in some mode, and we do check for all modes one by one.
        if mode_used != "sha256":
            key_to_update = PersonalAPIKey.objects.select_for_update().get(id=personal_api_key_object.id)
            key_to_update.secure_value = hash_key_value(personal_api_key)
            key_to_update.save(update_fields=["secure_value"])

        if source == "query string":
            PERSONAL_API_KEY_QUERY_PARAM_COUNTER.labels(personal_api_key_object.user.uuid).inc()

        return personal_api_key_object

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        personal_api_key_with_source = self.find_key_with_source(request)
        if not personal_api_key_with_source:
            return None

        personal_api_key_object = self.validate_key(personal_api_key_with_source)

        self.update_key_last_used_at(personal_api_key_object)
        assert personal_api_key_object.user is not None

        # :KLUDGE: CHMiddleware does not receive the correct user when authenticating by api key.
        tag_queries(
            user_id=personal_api_key_object.user.pk,
            team_id=personal_api_key_object.user.current_team_id,
            access_method=AccessMethod.PERSONAL_API_KEY,
            api_key_mask=personal_api_key_object.mask_value,
            api_key_label=personal_api_key_object.label,
        )

        self.personal_api_key = personal_api_key_object

        return personal_api_key_object.user, None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class ProjectSecretAPIKeyAuthentication(authentication.BaseAuthentication, APIKeyAuthentication):
    """
    Authenticates using a project secret API key. Unlike a personal API key, this is not associated with a
    user and should only be used for local_evaluation and flags remote_config (not to be confused with the
    other remote_config endpoint) requests. When authenticated, this returns a "synthetic"
    ProjectSecretAPIKeyUser object that has the team set. This allows us to use the existing permissioning
    system for local_evaluation and flags remote_config requests.

    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    """

    keyword = "Bearer"
    project_secret_api_key: Optional["ProjectSecretAPIKey"] = None

    @classmethod
    def find_secret_api_token(
        cls,
        request: Union[HttpRequest, Request],
    ) -> Optional[str]:
        """Try to find project secret API key in request and return it"""
        if "authorization" in request.headers:
            raw_header = request.headers["authorization"]
            header_value = raw_header.strip()

            authorization_match = re.match(rf"^{cls.keyword}\s+(phs_[a-zA-Z0-9]+)$", header_value)
            if authorization_match:
                token = authorization_match.group(1).strip()
                return token

        # Wrap HttpRequest in DRF Request if needed
        if not isinstance(request, Request):
            request = Request(request)

        data = request.data

        if data and "secret_api_key" in data:
            return data["secret_api_key"]
        elif data and "project_secret_api_key" in data:
            return data["project_secret_api_key"]

        return None

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        secret_api_token = self.find_secret_api_token(request)

        if not secret_api_token:
            return None

        project_secret_api_key_result = ProjectSecretAPIKey.find_project_secret_api_key(secret_api_token)

        if project_secret_api_key_result:
            project_secret_api_key, _ = project_secret_api_key_result
            self.project_secret_api_key = project_secret_api_key

            self.update_key_last_used_at(project_secret_api_key)

            tag_queries(
                team_id=project_secret_api_key.team_id,
                access_method=AccessMethod.PROJECT_SECRET_API_KEY,
                api_key_mask=project_secret_api_key.mask_value,
                api_key_label=project_secret_api_key.label,
            )

            return (ProjectSecretAPIKeyUser(project_secret_api_key.team, project_secret_api_key), None)

        # For backwards compat with feature flags - fallback to team secret_api_token
        try:
            Team = apps.get_model(app_label="posthog", model_name="Team")
            team = Team.objects.get_team_from_cache_or_secret_api_token(secret_api_token)

            if team is None:
                return None

            # Team secret token = full access, no project_secret_api_key object
            return (ProjectSecretAPIKeyUser(team, None), None)
        except Team.DoesNotExist:
            return None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class ProjectSecretAPIKeyUser(AnonymousUser):
    """
    A "synthetic" user object returned by the ProjectSecretAPIKeyAuthentication when authenticating with a project secret API key.
    """

    pk: int  # type: ignore[assignment]
    id: int  # type: ignore[assignment]

    def __init__(self, team, project_secret_api_key: Optional["ProjectSecretAPIKey"] = None):
        self.pk = -1
        self.id = -1
        self.team = team
        self.current_team_id = team.id
        self.project_secret_api_key = project_secret_api_key
        self.distinct_id = (
            f"ph_secret_project_key:{self.project_secret_api_key.id}"
            if self.project_secret_api_key
            else "team_secret_api_token"
        )
        self.email = None

    def __str__(self):
        return f"ProjectSecretAPIKeyUser in project {self.current_team_id}"

    @property
    def is_authenticated(self):
        return True

    def has_perm(self, perm, obj=None):
        return False

    def has_module_perms(self, app_label):
        return False


class TemporaryTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request: Request):
        # if the Origin is different, the only authentication method should be temporary_token
        # This happens when someone is trying to create actions from the editor on their own website
        if (
            request.headers.get("Origin")
            and urlsplit(request.headers["Origin"]).netloc not in urlsplit(request.build_absolute_uri("/")).netloc
        ):
            if not request.GET.get("temporary_token"):
                raise AuthenticationFailed(
                    detail="No temporary_token set. "
                    + "That means you're either trying to access this API from a different site, "
                    + "or it means your proxy isn't sending the correct headers. "
                    + "See https://posthog.com/docs/deployment/running-behind-proxy for more information."
                )
        if request.GET.get("temporary_token"):
            User = apps.get_model(app_label="posthog", model_name="User")
            user = User.objects.filter(is_active=True, temporary_token=request.GET.get("temporary_token"))
            if not user.exists():
                raise AuthenticationFailed(detail="User doesn't exist")
            return (user.first(), None)

        return None

    # NOTE: This appears first in the authentication chain often so we want to define an authenticate_header to ensure 401 and not 403
    def authenticate_header(self, request: Request):
        return "Bearer"


class JwtAuthentication(authentication.BaseAuthentication):
    """
    A way of authenticating with a JWT, primarily by background jobs impersonating a User
    """

    keyword = "Bearer"

    @classmethod
    def authenticate(cls, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
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
                sharing_configuration = SharingConfiguration.objects.get(
                    access_token=sharing_access_token, enabled=True
                )

                # If password is required, don't authenticate via direct access_token
                # Let the view handle showing the unlock page
                if sharing_configuration.password_required:
                    return None

            except SharingConfiguration.DoesNotExist:
                raise AuthenticationFailed(detail="Sharing access token is invalid.")
            else:
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

            share_password = SharePassword.objects.select_related("sharing_configuration").get(
                id=payload["share_password_id"],
                sharing_configuration__team_id=payload["team_id"],
                sharing_configuration__enabled=True,
                sharing_configuration__password_required=True,
                is_active=True,
            )

            sharing_configuration = share_password.sharing_configuration

            # Verify the access token matches (prevents token reuse across different shares)
            if sharing_configuration.access_token != payload.get("access_token"):
                return None

            self.sharing_configuration = sharing_configuration
            self.share_password = share_password
            return (AnonymousUser(), None)

        except jwt.InvalidTokenError:
            # Expected: JWT decode failed (likely a personal API key was passed)
            # Let the next authenticator (PersonalAPIKeyAuthentication) handle it
            return None
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
        authorization_token = self._extract_token(request)

        if not authorization_token:
            return None

        try:
            access_token = self._validate_token(authorization_token)

            if not access_token:
                raise AuthenticationFailed(detail="Invalid access token.")

            self.access_token = access_token

            tag_queries(
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
