import functools
import re
from datetime import timedelta
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import urlsplit

import jwt
from django.apps import apps
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.clickhouse.query_tagging import tag_queries
from posthog.jwt import PosthogJwtAudience, decode_jwt
from posthog.models.personal_api_key import hash_key_value
from posthog.models.sharing_configuration import SharingConfiguration
from posthog.models.user import User
from django.contrib.auth.models import AnonymousUser


class PersonalAPIKeyAuthentication(authentication.BaseAuthentication):
    """A way of authenticating with personal API keys.
    Only the first key candidate found in the request is tried, and the order is:
    1. Request Authorization header of type Bearer.
    2. Request body.
    3. Request query string.
    """

    keyword = "Bearer"

    @classmethod
    def find_key_with_source(
        cls,
        request: Union[HttpRequest, Request],
        request_data: Optional[Dict[str, Any]] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str]]:
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
        request_data: Optional[Dict[str, Any]] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Try to find personal API key in request and return it."""
        key_with_source = cls.find_key_with_source(request, request_data, extra_data)
        return key_with_source[0] if key_with_source is not None else None

    @classmethod
    def authenticate(cls, request: Union[HttpRequest, Request]) -> Optional[Tuple[Any, None]]:
        from posthog.models import PersonalAPIKey

        personal_api_key_with_source = cls.find_key_with_source(request)
        if not personal_api_key_with_source:
            return None
        personal_api_key, source = personal_api_key_with_source
        secure_value = hash_key_value(personal_api_key)
        try:
            personal_api_key_object = (
                PersonalAPIKey.objects.select_related("user")
                .filter(user__is_active=True)
                .get(secure_value=secure_value)
            )
        except PersonalAPIKey.DoesNotExist:
            raise AuthenticationFailed(detail=f"Personal API key found in request {source} is invalid.")

        now = timezone.now()
        key_last_used_at = personal_api_key_object.last_used_at
        # Only updating last_used_at if the hour's changed
        # This is to avooid excessive UPDATE queries, while still presenting accurate (down to the hour) info in the UI
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
        request.using_personal_api_key = True  # type: ignore
        return personal_api_key_object.user, None

    @classmethod
    def authenticate_header(cls, request) -> str:
        return cls.keyword


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


class JwtAuthentication(authentication.BaseAuthentication):
    """
    A way of authenticating with a JWT, primarily by background jobs impersonating a User
    """

    keyword = "Bearer"

    @classmethod
    def authenticate(cls, request: Union[HttpRequest, Request]) -> Optional[Tuple[Any, None]]:
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

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[Tuple[Any, Any]]:
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


def authenticate_secondarily(endpoint):
    """
    DEPRECATED: Used for supporting legacy endpoints not on DRF.
    Authentication for function views.
    """

    @functools.wraps(endpoint)
    def wrapper(request: HttpRequest):
        if not request.user.is_authenticated:
            try:
                auth_result = PersonalAPIKeyAuthentication.authenticate(request)
                if isinstance(auth_result, tuple) and auth_result[0].__class__.__name__ == "User":
                    request.user = auth_result[0]
                else:
                    raise AuthenticationFailed("Authentication credentials were not provided.")
            except AuthenticationFailed as e:
                return JsonResponse({"detail": e.detail}, status=401)
        return endpoint(request)

    return wrapper
