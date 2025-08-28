"""
Cached authentication backend for high-traffic API endpoints.

This module provides a Django REST Framework authentication class that uses
the team access token cache to authenticate requests without database calls.
"""

import logging
from typing import Any, Optional, Union

from django.http import HttpRequest

from prometheus_client import Counter, Histogram
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication, SecuredSDKEndpointUser
from posthog.clickhouse.query_tagging import tag_queries
from posthog.storage.team_access_cache import team_access_cache, team_access_tokens_hypercache

logger = logging.getLogger(__name__)

# Prometheus metrics
CACHED_AUTH_OPERATIONS = Counter(
    "posthog_cached_auth_operations_total",
    "Number of cached authentication operations",
    labelnames=["result", "token_type"],
)

CACHED_AUTH_LATENCY = Histogram(
    "posthog_cached_auth_latency_seconds", "Latency of cached authentication operations", labelnames=["result"]
)


class MinimalTeam:
    """
    Minimal team object synthesized from cached data.

    This class provides the minimum team properties needed for authentication
    without requiring a database query. It's compatible with the Team interface
    used by SecuredSdkEndpointUser.
    """

    def __init__(self, api_token: str, team_id: int):
        self.api_token = api_token
        self.id = team_id
        self.pk = team_id  # Django models use both .id and .pk

    def __str__(self):
        return f"MinimalTeam(id={self.id}, api_token='{self.api_token[:8]}...')"

    def __repr__(self):
        return self.__str__()


class LocalEvaluationAuthentication(authentication.BaseAuthentication):
    """
    Cached authentication for local evaluation API endpoints.

    This authentication class attempts to validate tokens using the team access
    token cache. It's designed to achieve zero-database-call authentication for
    local evaluation endpoints that receive high traffic volumes.

    Only personal API keys with feature flag read access are allowed through
    this authentication method.

    Authentication flow:
    1. Extract project API key and access token from request
    2. Check if access token is cached as authorized for the team
    3. If found in cache: return authenticated team without DB call
    4. If not found: return None and let the next authentication handle it
    """

    keyword = "Bearer"

    def authenticate(self, request: Union[HttpRequest, Request]) -> Optional[tuple[Any, Any]]:
        """
        Authenticate the request using cached token validation.

        Args:
            request: The incoming HTTP request

        Returns:
            Tuple of (user, auth) if authenticated, None if not applicable

        Raises:
            AuthenticationFailed: If authentication fails definitively
        """
        with CACHED_AUTH_LATENCY.labels(result="total").time():
            try:
                # Extract tokens from request
                tokens = self._extract_tokens(request)
                if not tokens:
                    return None  # No applicable tokens found

                project_api_key, access_token, token_type = tokens

                # Attempt cached authentication
                user = self._authenticate_with_cache(project_api_key, access_token, token_type)

                if user is not None:
                    # Cache hit - return the result
                    # Tag queries for monitoring
                    if hasattr(user, "team"):
                        team_id = user.team.id
                        # Use the token type to determine appropriate access method
                        access_method = token_type if token_type in ["personal_api_key", "secret_api_key"] else "oauth"
                        tag_queries(
                            team_id=team_id,
                            access_method=access_method,
                        )

                    CACHED_AUTH_OPERATIONS.labels(result="cache_hit", token_type=token_type).inc()

                    logger.debug(
                        f"Cached authentication successful for team {project_api_key}",
                        extra={"project_api_key": project_api_key, "token_type": token_type},
                    )
                    return user, None

                # Cache miss - fall through to standard authentication
                return None

            except AuthenticationFailed:
                # Let authentication failures bubble up
                raise
            except Exception as e:
                CACHED_AUTH_OPERATIONS.labels(result="error", token_type="unknown").inc()
                logger.warning(f"Error in cached authentication: {e}")

                # Fall through to standard authentication on unexpected errors
                return None

    def _extract_tokens(self, request: Union[HttpRequest, Request]) -> Optional[tuple[str, str, str]]:
        """
        Extract project API key and access token from request.

        Args:
            request: The HTTP request

        Returns:
            Tuple of (project_api_key, access_token, token_type) or None
        """
        try:
            # Try to get access token first (personal API key or secret API key)
            access_token_tuple = self._extract_access_token(request)
            if access_token_tuple is None:
                return None
            access_token, access_token_type = access_token_tuple

            # Try to get project API key from the request
            # This could be in query params, headers, or body depending on endpoint
            project_api_key = self._extract_project_api_key(request)

            if not project_api_key:
                return None

            return project_api_key, access_token, access_token_type

        except Exception as e:
            logger.debug(f"Error extracting tokens: {e}")
            return None

    def _extract_project_api_key(self, request: Union[HttpRequest, Request]) -> Optional[str]:
        """
        Extract project API key from request.

        This is typically in the request body or query params.
        """
        # Convert HttpRequest to DRF Request if needed
        if not isinstance(request, Request):
            request = Request(request)

        # Check request body first
        if hasattr(request, "data") and request.data:
            project_key = request.data.get("project_api_key") or request.data.get("api_key")
            if project_key:
                return project_key

        # Check query parameters
        project_key = request.GET.get("project_api_key") or request.GET.get("api_key") or request.GET.get("token")
        if project_key:
            return project_key

        return None

    def _extract_access_token(self, request: Union[HttpRequest, Request]) -> Optional[tuple[str, str]]:
        """
        Extract access token from request using existing authentication methods.

        This leverages the existing token extraction logic from PersonalAPIKeyAuthentication
        and ProjectSecretAPIKeyAuthentication.
        """
        # Try secret API key extraction
        secret_key = ProjectSecretAPIKeyAuthentication.find_secret_api_token(request)
        if secret_key:
            return secret_key, "secret_api_key"

        # Try personal API key extraction
        personal_key = PersonalAPIKeyAuthentication.find_key(request)
        if personal_key:
            return personal_key, "personal_api_key"

        return None

    def _authenticate_with_cache(
        self, project_api_key: str, access_token: str, token_type: str
    ) -> Optional[SecuredSDKEndpointUser]:
        """
        Attempt authentication using the team access token cache.

        Args:
            project_api_key: Team's project API key
            access_token: Access token to validate
            token_type: Type of access token

        Returns:
            User if cached auth successful, None if cache miss
        """
        try:
            # Check access and get team data in a single cache lookup
            has_access, team = team_access_cache.has_access_with_team(project_api_key, access_token)

            if not has_access:
                # Cache miss or token not authorized
                return None

            # Token is cached and authorized - get team object
            if not team:
                # This should never happen, but we'll log it just in case
                logger.warning(f"Team not found for authentication", extra={"project_api_key": project_api_key})
                return None

            return SecuredSDKEndpointUser(team)
        except Exception as e:
            logger.warning(f"Error in cached authentication: {e}")
            return None

    def _get_team_from_cache_metadata(self, project_api_key: str) -> Optional[MinimalTeam]:
        """
        Extract team metadata from the access token cache to create a minimal team object.

        This method reads the enhanced cache structure that includes team_id,
        enabling zero-database-call authentication when the cache is warmed.

        Args:
            project_api_key: Team's project API key

        Returns:
            MinimalTeam object if cache contains team metadata, None otherwise
        """
        try:
            if not project_api_key:
                return None

            # Get team access token data from HyperCache
            token_data = team_access_tokens_hypercache.get_from_cache(project_api_key)
            if not token_data:
                return None

            # Extract team metadata from cache
            team_id = token_data.get("team_id")
            if not team_id:
                logger.debug(f"No team_id found in cache for {project_api_key}")
                return None

            # Create minimal team object from cached metadata
            return MinimalTeam(api_token=project_api_key, team_id=team_id)

        except Exception as e:
            logger.debug(f"Error extracting team from cache metadata: {e}")
            return None

    def _get_personal_api_key_from_token(self, access_token: str):
        """
        Get personal API key object from the raw token value.

        Args:
            access_token: The raw personal API key token

        Returns:
            PersonalAPIKey object if found, None otherwise
        """
        try:
            # Import moved to top of function to avoid repeated imports
            from posthog.models.personal_api_key import find_personal_api_key

            result = find_personal_api_key(access_token)
            return result[0] if result else None
        except Exception as e:
            logger.warning(f"Error getting personal API key: {e}")
            return None

    def _has_feature_flag_access(self, personal_api_key) -> bool:
        """
        Check if a personal API key has feature flag read access.

        Args:
            personal_api_key: PersonalAPIKey object

        Returns:
            True if the key has feature flag read access, False otherwise
        """
        try:
            # Legacy keys (no scopes) are allowed for backward compatibility
            if not personal_api_key.scopes:
                return True

            # Check for wildcard access
            if "*" in personal_api_key.scopes:
                return True

            # Check for specific feature flag read access
            # Also check for write access (write implies read)
            return "feature_flag:read" in personal_api_key.scopes or "feature_flag:write" in personal_api_key.scopes
        except Exception as e:
            logger.warning(f"Error checking feature flag access: {e}")
            return False

    @classmethod
    def authenticate_header(cls, request) -> str:
        """Return the authentication header keyword."""
        return cls.keyword
