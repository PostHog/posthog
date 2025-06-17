import functools
import re
from datetime import timedelta
from typing import Any, Optional, Union
from urllib.parse import urlsplit

import jwt
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.clickhouse.query_tagging import tag_queries
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models.oauth import OAuthAccessToken
from posthog.models.personal_api_key import (
    PersonalAPIKey,
    hash_key_value,
    PERSONAL_API_KEY_MODES_TO_TRY,
)
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from django.contrib.auth.models import AnonymousUser
from zxcvbn import zxcvbn


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
    """

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

    message = "Invalid personal API key."

    @classmethod
    def find_key_with_source(
        cls,
        request: Union[HttpRequest, Request],
        request_data: Optional[dict[str, Any]] = None,
        extra_data: Optional[dict[str, Any]] = None,
    ) -> Optional[tuple[str, str]]:
        """Try to find personal API key in request and return it along with where it was found."""
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(rf"^{cls.keyword}\s+(\S.+)$", request.META["HTTP_AUTHORIZATION"])
            if authorization_match:
                return authorization_match.group(1).strip(), "Authorization header"
        data = request.data if request_data is None and isinstance(request, Request) else request_data

        if data and "personal_api_key" in data:
            return data["personal_api_key"], "body"
        if "personal_api_key" in request.GET:
            return request.GET["personal_api_key"], "query string"
        if extra_data and "personal_api_key" in extra_data:
            # compatibility with /capture endpoint
            return extra_data["personal_api_key"], "query string data"
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

        return personal_api_key_object

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        personal_api_key_with_source = self.find_key_with_source(request)
        if not personal_api_key_with_source:
            return None

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
        tag_queries(
            user_id=personal_api_key_object.user.pk,
            team_id=personal_api_key_object.user.current_team_id,
            access_method="personal_api_key",
        )

        self.personal_api_key = personal_api_key_object

        return personal_api_key_object.user, None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class ProjectSecretAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticates using a project secret API key. Unlike a personal API key, this is not associated with a
    user and should only be used for local_evaluation and flags remote_config (not to be confused with the
    other remote_config endpoint) requests. When authenticated, this returns a "synthetic"
    ProjectSecretAPIKeyUser object that has the team set. This allows us to use the existing permissioning
    system for local_evaluation and flags remote_config requests.

    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    3. Request query string.
    """

    keyword = "Bearer"

    @classmethod
    def find_secret_api_token(
        cls,
        request: Union[HttpRequest, Request],
    ) -> Optional[str]:
        """Try to find project secret API key in request and return it"""
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(rf"^{cls.keyword}\s+(phs_[a-zA-Z0-9]+)$", request.META["HTTP_AUTHORIZATION"])
            if authorization_match:
                return authorization_match.group(1).strip()

        # Wrap HttpRequest in DRF Request if needed
        if not isinstance(request, Request):
            request = Request(request)

        data = request.data

        if data and "secret_api_key" in data:
            return data["secret_api_key"]

        if "secret_api_key" in request.GET:
            return request.GET["secret_api_key"]

        return None

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, None]]:
        secret_api_token = self.find_secret_api_token(request)

        if not secret_api_token:
            return None

        # get the team from the secret api key
        try:
            Team = apps.get_model(app_label="posthog", model_name="Team")
            team = Team.objects.get_team_from_cache_or_secret_api_token(secret_api_token)

            if team is None:
                return None

            # Secret api keys are not associated with a user, so we create a ProjectSecretAPIKeyUser
            # and attach the team. The team is the important part here.
            return (ProjectSecretAPIKeyUser(team), None)
        except Team.DoesNotExist:
            return None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


class ProjectSecretAPIKeyUser:
    """
    A "synthetic" user object returned by the ProjectSecretAPIKeyAuthentication when authenticating with a project secret API key.
    """

    def __init__(self, team):
        self.team = team
        self.current_team_id = team.id
        self.is_authenticated = True
        self.pk = -1

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
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(rf"^Bearer\s+(\S.+)$", request.META["HTTP_AUTHORIZATION"])
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
            except SharingConfiguration.DoesNotExist:
                raise AuthenticationFailed(detail="Sharing access token is invalid.")
            else:
                self.sharing_configuration = sharing_configuration
                return (AnonymousUser(), None)
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
                return None  # We return None here because we want to let the next authentication method have a go

            self.access_token = access_token

            tag_queries(
                user_id=access_token.user.pk,
                team_id=access_token.user.current_team_id,
                access_method="oauth",
            )

            return access_token.user, None

        except AuthenticationFailed:
            raise
        except Exception:
            raise AuthenticationFailed(detail="Invalid access token.")

    def _extract_token(self, request: Union[HttpRequest, Request]) -> Optional[str]:
        if "HTTP_AUTHORIZATION" in request.META:
            authorization_match = re.match(rf"^{self.keyword}\s+(\S.+)$", request.META["HTTP_AUTHORIZATION"])
            if authorization_match:
                return authorization_match.group(1).strip()
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


def authenticate_secondarily(endpoint):
    """
    DEPRECATED: Used for supporting legacy endpoints not on DRF.
    Authentication for function views.
    """

    @functools.wraps(endpoint)
    def wrapper(request: HttpRequest):
        if not request.user.is_authenticated:
            try:
                auth_result = PersonalAPIKeyAuthentication().authenticate(request)
                if isinstance(auth_result, tuple) and auth_result[0].__class__.__name__ == "User":
                    request.user = auth_result[0]
                else:
                    raise AuthenticationFailed("Authentication credentials were not provided.")
            except AuthenticationFailed as e:
                return JsonResponse({"detail": e.detail}, status=401)
        return endpoint(request)

    return wrapper
