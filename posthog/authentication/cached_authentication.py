"""
Cached authentication backend for high-traffic API endpoints.

This module provides a Django REST Framework authentication class that uses
the team access token cache to authenticate requests without database calls.
"""

import logging
import re
from typing import Any, Optional, Union

from django.http import HttpRequest
from prometheus_client import Counter, Histogram
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import (
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    ProjectSecretAPIKeyUser,
)
from posthog.clickhouse.query_tagging import tag_queries
from posthog.storage.team_access_cache import team_access_cache

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

# Cached authentication is always enabled - fallback to regular auth provides safety


def _validate_token_format(token: str) -> bool:
    """
    Validate that a token has a valid format.

    Args:
        token: The token to validate

    Returns:
        True if the token format is valid, False otherwise
    """
    if not token or not isinstance(token, str):
        return False

    # Check minimum length (10 characters as per Team model validation)
    if len(token) < 10:
        return False

    # Check maximum reasonable length to prevent abuse
    if len(token) > 200:
        return False

    # Check for only allowed characters (alphanumeric, underscore, hyphen)
    if not re.match(r"^[a-zA-Z0-9_-]+$", token):
        return False

    return True


def _get_token_type(token: str) -> Optional[str]:
    """
    Determine the type of token based on its format.

    Args:
        token: The token to analyze

    Returns:
        The token type or None if unrecognized
    """
    if not _validate_token_format(token):
        return None

    # Project API tokens start with "phc_"
    if token.startswith("phc_"):
        return "project_api_key"

    # Personal API keys start with "phx_"
    if token.startswith("phx_"):
        return "personal_api_key"

    # Secret API keys start with "phs_"
    if token.startswith("phs_"):
        return "secret_api_key"

    # Legacy tokens without prefixes exist but are uncommon
    # Default to project_api_key for backward compatibility
    return "project_api_key"


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
                cached_result = self._authenticate_with_cache(project_api_key, access_token, token_type)

                if cached_result is not None:
                    # Cache hit - return the result
                    user, auth = cached_result

                    # Tag queries for monitoring
                    if hasattr(user, "team"):
                        team_id = user.team.id
                        # Use the token type to determine appropriate access method
                        access_method = "personal_api_key" if token_type == "personal_api_key" else "oauth"
                        tag_queries(
                            team_id=team_id,
                            access_method=access_method,
                        )

                    CACHED_AUTH_OPERATIONS.labels(result="cache_hit", token_type=token_type).inc()

                    logger.debug(
                        f"Cached authentication successful for team {project_api_key}",
                        extra={"project_api_key": project_api_key, "token_type": token_type},
                    )

                    return user, auth

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
            # Try to get project API key from the request
            # This could be in query params, headers, or body depending on endpoint
            project_api_key = self._extract_project_api_key(request)
            if not project_api_key:
                return None

            # Try to get access token (personal API key or secret API key)
            access_token = self._extract_access_token(request)
            if not access_token:
                return None

            # Validate token formats
            if not _validate_token_format(project_api_key):
                return None

            if not _validate_token_format(access_token):
                return None

            # Validate project API key has correct prefix
            if not project_api_key.startswith("phc_"):
                return None

            # Determine token type
            access_token_type = _get_token_type(access_token)
            if not access_token_type:
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
        project_key = request.GET.get("project_api_key") or request.GET.get("api_key")
        if project_key:
            return project_key

        return None

    def _extract_access_token(self, request: Union[HttpRequest, Request]) -> Optional[str]:
        """
        Extract access token from request using existing authentication methods.

        This leverages the existing token extraction logic from PersonalAPIKeyAuthentication
        and ProjectSecretAPIKeyAuthentication.
        """
        # Try personal API key extraction
        personal_key = PersonalAPIKeyAuthentication.find_key(request)
        if personal_key:
            return personal_key

        # Try secret API key extraction
        secret_key = ProjectSecretAPIKeyAuthentication.find_secret_api_token(request)
        if secret_key:
            return secret_key

        return None

    def _authenticate_with_cache(
        self, project_api_key: str, access_token: str, token_type: str
    ) -> Optional[tuple[Any, Any]]:
        """
        Attempt authentication using the team access token cache.

        Args:
            project_api_key: Team's project API key
            access_token: Access token to validate
            token_type: Type of access token

        Returns:
            Tuple of (user, auth) if cached auth successful, None if cache miss
        """
        try:
            # Check if the access token is authorized for this team
            has_access = team_access_cache.has_access(project_api_key, access_token)

            if not has_access:
                # Cache miss or token not authorized
                return None

            # Token is cached and authorized - create synthetic user
            # We need to get the team object to create the user
            team = self._get_team_from_cache_or_db(project_api_key)
            if not team:
                logger.warning(f"Team not found for project API key: {project_api_key}")
                return None

            # Create appropriate user object based on token type
            if token_type in ["personal_api_key"]:
                # For personal API keys in cached auth, we still need to verify
                # the scope at authentication time. If the token is in cache,
                # it means it had the right scope when cached, but we should
                # validate again to be safe.

                # Get the personal API key from database for scope verification
                personal_api_key = self._get_personal_api_key_from_token(access_token)
                if not personal_api_key:
                    logger.warning(f"Personal API key not found for cached token")
                    return None

                # Verify the key has feature flag read access
                if not self._has_feature_flag_access(personal_api_key):
                    logger.warning(f"Personal API key lacks feature flag read access")
                    return None

                # Return the user associated with the personal API key
                return personal_api_key.user, None

            elif token_type in ["secret_api_key", "project_api_key"]:
                # For secret API keys, create synthetic user
                user = ProjectSecretAPIKeyUser(team)
                return user, None

            else:
                logger.warning(f"Unknown token type for cached auth: {token_type}")
                return None

        except Exception as e:
            logger.warning(f"Error in cached authentication: {e}")
            return None

    def _get_team_from_cache_or_db(self, project_api_key: str):
        """
        Get team object, preferring cache but falling back to DB.

        This uses the existing team caching mechanism.
        """
        try:
            # Import moved to top of function to avoid repeated imports
            from posthog.models.team.team import Team

            return Team.objects.get_team_from_cache_or_token(project_api_key)
        except Exception as e:
            logger.warning(f"Error getting team for {project_api_key}: {e}")
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
