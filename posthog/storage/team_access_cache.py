"""
Per-team access token cache layer for cache-based authentication.

This module provides Redis-based caching of hashed access tokens per team,
enabling zero-database-call authentication for the local_evaluation endpoint.
"""

import logging
from datetime import UTC
from typing import TYPE_CHECKING, Any, Optional

from prometheus_client import Counter, Histogram

from posthog.models.personal_api_key import hash_key_value
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

if TYPE_CHECKING:
    from posthog.authentication.cached_authentication import MinimalTeam

logger = logging.getLogger(__name__)

# Prometheus metrics
TEAM_ACCESS_CACHE_OPERATIONS = Counter(
    "posthog_team_access_cache_operations_total",
    "Number of team access cache operations",
    labelnames=["operation", "result", "token_status", "source"],
)

TEAM_ACCESS_CACHE_LATENCY = Histogram(
    "posthog_team_access_cache_latency_seconds", "Latency of team access cache operations", labelnames=["operation"]
)

# Cache configuration
DEFAULT_TTL = 300  # 5 minutes
CACHE_KEY_PREFIX = "cache/teams"


class TeamAccessTokenCache:
    """
    HyperCache-based cache for per-team access token lists.

    This class manages hashed token lists per team to enable fast authentication
    lookups without database queries. Each team has its own cache entry with
    JSON data containing hashed authorized tokens and metadata. Uses HyperCache
    for automatic Redis + S3 backup and improved reliability.
    """

    def __init__(self, ttl: int = DEFAULT_TTL):
        """
        Initialize the team access token cache.

        Args:
            ttl: Time-to-live for cache entries in seconds
        """
        self.ttl = ttl

    def has_access_with_team(self, project_api_key: str, access_token: str) -> tuple[bool, Optional["MinimalTeam"]]:
        """
        Check if an access token is authorized for the given team and return team data.

        This method combines token validation and team metadata extraction in a single
        cache lookup, avoiding redundant cache calls in the authentication flow.

        Args:
            project_api_key: The team's project API key
            access_token: The access token to validate

        Returns:
            Tuple of (has_access, minimal_team) where:
            - has_access: True if the token is authorized, False otherwise
            - minimal_team: MinimalTeam object if authorized and team_id available, None otherwise
        """
        with TEAM_ACCESS_CACHE_LATENCY.labels(operation="has_access_with_team").time():
            try:
                # Hash the access token for comparison
                hashed_token = hash_key_value(access_token, mode="sha256")

                # Get the team's token data from HyperCache
                token_data, source = team_access_tokens_hypercache.get_from_cache_with_source(project_api_key)

                if token_data is None:
                    TEAM_ACCESS_CACHE_OPERATIONS.labels(
                        operation="has_access_with_team", result="cache_miss", token_status="unknown", source="cache"
                    ).inc()
                    logger.debug(f"Cache miss for team {project_api_key}, attempting to warm cache")

                    # Attempt to warm the cache and try again
                    try:
                        warm_result = warm_team_token_cache(project_api_key)
                        if warm_result:
                            # Try to get the data again after warming
                            token_data, source = team_access_tokens_hypercache.get_from_cache_with_source(
                                project_api_key
                            )
                    except Exception as e:
                        logger.warning(f"Failed to warm cache for team {project_api_key}: {e}")

                    # If we still don't have data after warming, return False, None
                    if token_data is None:
                        logger.debug(f"Cache still empty after warming for team {project_api_key}")
                        return False, None

                # Check if the hashed token exists in the list
                # token_data is guaranteed to not be None at this point
                hashed_tokens = token_data.get("hashed_tokens", [])
                has_token = hashed_token in hashed_tokens

                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="has_access_with_team",
                    result="cache_hit",
                    token_status="found" if has_token else "not_found",
                    source=source,
                ).inc()

                if has_token:
                    logger.debug(f"Token authorized for team {project_api_key}")

                    # Extract team metadata for MinimalTeam creation
                    team_id = token_data.get("team_id")
                    if team_id:
                        # Import here to avoid circular imports
                        from posthog.authentication.cached_authentication import MinimalTeam

                        minimal_team = MinimalTeam(api_token=project_api_key, team_id=team_id)
                        return True, minimal_team
                    else:
                        logger.debug(f"No team_id found in cache for {project_api_key}")
                        return True, None
                else:
                    logger.debug(f"Token not authorized for team {project_api_key}")
                    return False, None

            except Exception as e:
                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="has_access_with_team", result="error", token_status="unknown", source="cache"
                ).inc()
                logger.warning(f"Error checking access with team for team {project_api_key}: {e}")
                return False, None

    def update_team_tokens(self, project_api_key: str, team_id: int, hashed_tokens: list[str]) -> None:
        """
        Update a team's complete token list in cache.

        Args:
            project_api_key: The team's project API key
            team_id: The team's ID
            hashed_tokens: List of hashed tokens (already in sha256$ format)
        """
        with TEAM_ACCESS_CACHE_LATENCY.labels(operation="update_team_tokens").time():
            try:
                from datetime import datetime

                # Build structured data for HyperCache
                token_data = {
                    "hashed_tokens": hashed_tokens,
                    "last_updated": datetime.now(UTC).isoformat(),
                    "team_id": team_id,  # Always include team_id for zero-DB-call authentication
                }

                # Store via HyperCache (handles Redis + S3 automatically)
                team_access_tokens_hypercache.set_cache_value(project_api_key, token_data)

                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="update_team_tokens", result="success", token_status="updated", source="database"
                ).inc()

                logger.info(
                    f"Updated token cache for team {project_api_key} with {len(hashed_tokens)} tokens",
                    extra={"team_project_api_key": project_api_key, "token_count": len(hashed_tokens)},
                )

            except Exception as e:
                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="update_team_tokens", result="error", token_status="failed", source="database"
                ).inc()
                logger.exception(f"Error updating tokens for team {project_api_key}: {e}")
                raise

    def invalidate_team(self, project_api_key: str) -> None:
        """
        Invalidate (delete) a team's token cache.

        Args:
            project_api_key: The team's project API key
        """
        with TEAM_ACCESS_CACHE_LATENCY.labels(operation="invalidate_team").time():
            try:
                # Clear from HyperCache (handles Redis + S3)
                team_access_tokens_hypercache.clear_cache(project_api_key)

                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="invalidate_team", result="success", token_status="invalidated", source="cache"
                ).inc()

                logger.info(f"Invalidated token cache for team {project_api_key}")

            except Exception as e:
                TEAM_ACCESS_CACHE_OPERATIONS.labels(
                    operation="invalidate_team", result="error", token_status="failed", source="cache"
                ).inc()
                logger.exception(f"Error invalidating cache for team {project_api_key}: {e}")
                raise

    def get_cached_token_count(self, project_api_key: str) -> Optional[int]:
        """
        Get the number of tokens cached for a team (for monitoring).

        Args:
            project_api_key: The team's project API key

        Returns:
            Number of cached tokens or None if not cached
        """
        try:
            token_data = team_access_tokens_hypercache.get_from_cache(project_api_key)

            if token_data is None:
                return None

            # Compute token count from array length (no need to store redundant field)
            return len(token_data.get("hashed_tokens", []))

        except Exception as e:
            logger.warning(f"Error getting token count for team {project_api_key}: {e}")
            return None


def _load_team_access_tokens(team_token: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    """
    Load team access tokens from the database.

    Args:
        team_token: Team identifier (can be Team object, API token string, or team ID)

    Returns:
        Dictionary containing hashed tokens and metadata, or HyperCacheStoreMissing if team not found
    """
    from datetime import datetime

    from posthog.models.personal_api_key import PersonalAPIKey
    from posthog.models.team.team import Team

    try:
        # Convert KeyType to team object if needed
        if isinstance(team_token, str):
            team = Team.objects.get(api_token=team_token)
        elif isinstance(team_token, int):
            team = Team.objects.get(id=team_token)
        else:
            # team_token is already a Team object
            team = team_token

        # Collect all hashed tokens for this team
        hashed_tokens = []

        # 1. Personal API keys with access to this team and feature flag read access

        # Get scoped keys that explicitly include this team and have feature flag read access
        scoped_keys = PersonalAPIKey.objects.filter(
            user__is_active=True, scoped_teams__contains=[team.id], scopes__contains=["feature_flag:read"]
        ).values_list("secure_value", flat=True)

        # Get unscoped keys (null/empty scoped_teams) from users in this team's organization
        # Only include keys with feature flag read access or legacy keys (no scopes)
        from django.db.models import Q

        from posthog.models.organization import OrganizationMembership

        unscoped_keys = (
            PersonalAPIKey.objects.filter(
                Q(scoped_teams__isnull=True) | Q(scoped_teams=[]),
                user__is_active=True,
                user__id__in=OrganizationMembership.objects.filter(organization_id=team.organization_id).values_list(
                    "user_id", flat=True
                ),
            )
            .filter(
                # Include keys that have feature flag read access OR legacy keys with no scopes
                Q(scopes__contains=["feature_flag:read"]) | Q(scopes__isnull=True) | Q(scopes=[])
            )
            .values_list("secure_value", flat=True)
        )

        # Combine both types of keys
        all_personal_keys = list(scoped_keys) + list(unscoped_keys)

        # Add personal API keys (already hashed in secure_value field)
        for secure_value in all_personal_keys:
            if secure_value:  # Ensure it's not None/empty
                hashed_tokens.append(secure_value)

        # 2. Team secret tokens (need to be hashed)
        if team.secret_api_token:
            hashed_secret = hash_key_value(team.secret_api_token, mode="sha256")
            hashed_tokens.append(hashed_secret)

        if team.secret_api_token_backup:
            hashed_secret_backup = hash_key_value(team.secret_api_token_backup, mode="sha256")
            hashed_tokens.append(hashed_secret_backup)

        # Return structured data for caching
        return {
            "hashed_tokens": hashed_tokens,
            "last_updated": datetime.now(UTC).isoformat(),
            "team_id": team.id,  # Include team_id for zero-DB-call authentication
        }

    except Team.DoesNotExist:
        logger.warning(f"Team not found for project API key: {team_token}")
        return HyperCacheStoreMissing()

    except Exception as e:
        logger.exception(f"Error loading team access tokens for {team_token}: {e}")
        return HyperCacheStoreMissing()


# HyperCache instance for team access tokens
team_access_tokens_hypercache = HyperCache(
    namespace="team_access_tokens",
    value="access_tokens.json",
    token_based=True,  # Use team API token as key
    load_fn=_load_team_access_tokens,
)

# Global instance for convenience
team_access_cache = TeamAccessTokenCache()


def warm_team_token_cache(project_api_key: str) -> bool:
    """
    Warm the token cache for a specific team by loading from database.

    This function now uses the HyperCache to update the cache, which handles
    both Redis and S3 storage automatically.

    Args:
        project_api_key: The team's project API key

    Returns:
        True if cache warming succeeded, False otherwise
    """
    # Use HyperCache to update the cache - this will call _load_team_access_tokens
    # It does not raise an exception if the cache is not updated, so we don't need to try/except
    success = team_access_tokens_hypercache.update_cache(project_api_key)

    if success:
        logger.info(
            f"Warmed token cache for team {project_api_key} using HyperCache",
            extra={"project_api_key": project_api_key},
        )
    else:
        logger.warning(f"Failed to warm token cache for team {project_api_key}")

    return success


def get_teams_needing_cache_refresh() -> list[str]:
    """
    Get a list of project API keys for teams that need cache refresh.

    This can be used by background tasks to identify teams whose
    token caches are missing from HyperCache.

    Returns:
        List of project API keys

    Raises:
        Exception: Database connectivity or other systemic issues that should trigger retries
    """
    from posthog.models.team.team import Team

    # Get all active teams - let database exceptions bubble up
    teams = Team.objects.filter(
        project__isnull=False  # Ensure team has a valid project
    ).values_list("api_token", flat=True)

    # Check which teams have missing caches in HyperCache
    teams_needing_refresh = []

    for project_api_key in teams:
        try:
            token_data = team_access_tokens_hypercache.get_from_cache(project_api_key)
            if token_data is None:
                teams_needing_refresh.append(project_api_key)
        except Exception as e:
            # Log individual team cache check failure but continue with others
            logger.warning(
                f"Failed to check cache for team {project_api_key}: {e}",
                extra={"project_api_key": project_api_key, "error": str(e)},
            )
            # Assume this team needs refresh if we can't check its cache
            teams_needing_refresh.append(project_api_key)

    return teams_needing_refresh


def get_teams_for_personal_api_key(personal_api_key_instance) -> list[str]:
    """
    Get project API keys for teams that a PersonalAPIKey has access to.

    Personal API keys can have access to multiple teams via scoped_teams.
    If scoped_teams is empty/null, the key has access to ALL teams within
    the user's organizations (following the same access pattern as the user).

    Args:
        personal_api_key_instance: The PersonalAPIKey instance

    Returns:
        List of project API keys (strings) for teams the key has access to
    """
    from posthog.models.team.team import Team

    scoped_teams = personal_api_key_instance.scoped_teams or []

    if scoped_teams:
        # Key is scoped to specific teams - return only those teams
        team_tokens = Team.objects.filter(id__in=scoped_teams).values_list("api_token", flat=True)
        return list(team_tokens)
    else:
        # Key is unscoped - has access to all teams within user's organizations
        from posthog.models.organization import OrganizationMembership

        # Get all organizations the user is a member of
        user_organizations = OrganizationMembership.objects.filter(user=personal_api_key_instance.user).values_list(
            "organization_id", flat=True
        )

        if user_organizations:
            # Get all teams in those organizations
            team_tokens = Team.objects.filter(organization_id__in=user_organizations).values_list(
                "api_token", flat=True
            )
            return list(team_tokens)
        else:
            # User has no organization memberships
            return []
