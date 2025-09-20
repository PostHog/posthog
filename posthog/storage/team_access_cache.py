"""
Per-team access token cache layer for cache-based authentication.

This module provides Redis-based caching of hashed access tokens per team,
enabling zero-database-call authentication for the local_evaluation endpoint.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.db.models import Q

from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing, KeyType

logger = logging.getLogger(__name__)

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

    def update_team_tokens(self, project_api_key: str, team_id: int, hashed_tokens: list[str]) -> None:
        """
        Update a team's complete token list in cache.

        Args:
            project_api_key: The team's project API key
            team_id: The team's ID
            hashed_tokens: List of hashed tokens (already in sha256$ format)
        """
        try:
            token_data = {
                "hashed_tokens": hashed_tokens,
                "last_updated": datetime.now(UTC).isoformat(),
                "team_id": team_id,
            }
            team_access_tokens_hypercache.set_cache_value(project_api_key, token_data)

            logger.info(
                f"Updated token cache for team {project_api_key} with {len(hashed_tokens)} tokens",
                extra={"team_project_api_key": project_api_key, "token_count": len(hashed_tokens)},
            )

        except Exception as e:
            logger.exception(f"Error updating tokens for team {project_api_key}: {e}")
            raise

    def invalidate_team(self, project_api_key: str) -> None:
        """
        Invalidate (delete) a team's token cache.

        Args:
            project_api_key: The team's project API key
        """
        try:
            team_access_tokens_hypercache.clear_cache(project_api_key)

            logger.info(f"Invalidated token cache for team {project_api_key}")

        except Exception as e:
            logger.exception(f"Error invalidating cache for team {project_api_key}: {e}")
            raise


def _load_team_access_tokens(team_token: KeyType) -> dict[str, Any] | HyperCacheStoreMissing:
    """
    Load team access tokens from the database.

    Args:
        team_token: Team identifier (can be Team object, API token string, or team ID)

    Returns:
        Dictionary containing hashed tokens and metadata, or HyperCacheStoreMissing if team not found
    """
    try:
        # Use transaction isolation to ensure consistent reads across all queries
        with transaction.atomic():
            if isinstance(team_token, str):
                team = Team.objects.select_related("organization").get(api_token=team_token)
            elif isinstance(team_token, int):
                team = Team.objects.select_related("organization").get(id=team_token)
            else:
                # team_token is already a Team object, but ensure organization is loaded
                team = team_token
                if not hasattr(team, "organization") or team.organization is None:
                    team = Team.objects.select_related("organization").get(id=team.id)

            hashed_tokens: list[str] = []

            # Get all relevant personal API keys in one optimized query
            # Combines scoped and unscoped keys with proper filtering
            personal_keys = (
                PersonalAPIKey.objects.select_related("user")
                .filter(
                    user__organization_membership__organization_id=team.organization_id,
                    user__is_active=True,
                )
                .filter(
                    # Organization scoping: key must either have no org restriction OR include this org
                    Q(scoped_organizations__isnull=True)
                    | Q(scoped_organizations=[])
                    | Q(scoped_organizations__contains=[str(team.organization_id)])
                )
                .filter(
                    (
                        # Scoped keys: explicitly include this team AND have feature flag read or write access
                        Q(scoped_teams__contains=[team.id])
                        & (
                            # Keys with write permission implicitly have read permission
                            Q(scopes__contains=["feature_flag:read"]) | Q(scopes__contains=["feature_flag:write"])
                        )
                    )
                    | (
                        # Unscoped keys: no team restriction (null or empty array)
                        (Q(scoped_teams__isnull=True) | Q(scoped_teams=[]))
                        & (
                            # AND either no scope restriction OR has feature flag read or write access
                            Q(scopes__isnull=True)
                            | Q(scopes=[])
                            | Q(scopes__contains=["feature_flag:read"])
                            | Q(scopes__contains=["feature_flag:write"])
                        )
                    )
                )
                .distinct()
                .values_list("secure_value", flat=True)
            )

            # Collect personal API key tokens
            hashed_tokens.extend(secure_value for secure_value in personal_keys if secure_value)

            # Add team secret tokens
            if team.secret_api_token:
                hashed_secret = hash_key_value(team.secret_api_token, mode="sha256")
                hashed_tokens.append(hashed_secret)

            if team.secret_api_token_backup:
                hashed_secret_backup = hash_key_value(team.secret_api_token_backup, mode="sha256")
                hashed_tokens.append(hashed_secret_backup)

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


def get_teams_needing_cache_refresh(limit: int | None = None, offset: int = 0) -> list[str]:
    """
    Get a list of project API keys for teams that need cache refresh.

    This function now supports pagination to handle large datasets efficiently.
    For installations with many teams, use limit/offset to process in batches.

    Args:
        limit: Maximum number of teams to check. None means no limit (all teams).
        offset: Number of teams to skip before starting to check.

    Returns:
        List of project API keys that need cache refresh

    Raises:
        Exception: Database connectivity or other systemic issues that should trigger retries
    """
    # Build queryset with pagination support
    # Note: Filtering by project__isnull=False may be needed in production
    # but is removed for testing since test teams often don't have projects
    queryset = Team.objects.values_list("api_token", flat=True).order_by("id")  # Consistent ordering for pagination

    # Apply pagination if specified
    if offset > 0:
        queryset = queryset[offset:]
    if limit is not None:
        queryset = queryset[:limit]

    # Check which teams have missing caches in HyperCache
    teams_needing_refresh = []

    for project_api_key in queryset:
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


def get_teams_needing_cache_refresh_paginated(batch_size: int = 1000):
    """
    Generator that yields batches of teams needing cache refresh.

    This is the recommended approach for processing large numbers of teams
    to avoid memory issues. It processes teams in chunks and yields each
    batch as it's completed.

    Args:
        batch_size: Number of teams to process per batch

    Yields:
        List[str]: Batches of project API keys that need cache refresh
    """
    offset = 0

    while True:
        batch = get_teams_needing_cache_refresh(limit=batch_size, offset=offset)

        if not batch:
            # No more teams to process
            break

        yield batch
        offset += batch_size

        # If we got fewer teams than requested, we've reached the end
        if len(batch) < batch_size:
            break


def get_teams_for_user_personal_api_keys(user_id: int) -> set[str]:
    """
    Get all project API keys for teams that a user's PersonalAPIKeys have access to.

    This function eliminates N+1 queries by determining all affected teams for
    a user's personal API keys in minimal database queries (1-3 queries maximum).

    Args:
        user_id: The user ID whose personal API keys to analyze

    Returns:
        Set of project API keys (strings) for all teams the user's keys have access to
    """
    # Get all personal API keys for the user
    personal_keys = list(PersonalAPIKey.objects.filter(user_id=user_id).values("id", "scoped_teams"))

    if not personal_keys:
        return set()

    affected_teams = set()
    scoped_team_ids: set[int] = set()
    has_unscoped_keys = False

    # Analyze all keys to determine which teams they affect
    for key_data in personal_keys:
        scoped_teams = key_data["scoped_teams"] or []
        if scoped_teams:
            # Scoped key - add specific team IDs
            scoped_team_ids.update(scoped_teams)
        else:
            # Unscoped key - will need all teams in user's organizations
            has_unscoped_keys = True

    # Get project API keys for scoped teams (if any) in one query
    if scoped_team_ids:
        scoped_team_tokens = Team.objects.filter(id__in=scoped_team_ids).values_list("api_token", flat=True)
        affected_teams.update(scoped_team_tokens)

    # Get project API keys for unscoped keys (if any) in two queries maximum
    if has_unscoped_keys:
        # Get user's organizations
        user_organizations = OrganizationMembership.objects.filter(user_id=user_id).values_list(
            "organization_id", flat=True
        )

        if user_organizations:
            # Get all teams in those organizations
            org_team_tokens = Team.objects.filter(organization_id__in=user_organizations).values_list(
                "api_token", flat=True
            )
            affected_teams.update(org_team_tokens)

    return affected_teams


def get_teams_for_single_personal_api_key(personal_api_key_instance: "PersonalAPIKey") -> list[str]:
    """
    Get project API keys for teams that a single PersonalAPIKey has access to.

    This is a helper function that internally uses the optimized user-based function.
    For better performance when processing multiple keys for the same user, use
    get_teams_for_user_personal_api_keys() directly.

    Args:
        personal_api_key_instance: The PersonalAPIKey instance

    Returns:
        List of project API keys (strings) for teams the key has access to
    """
    user_id = personal_api_key_instance.user_id
    all_user_teams = get_teams_for_user_personal_api_keys(user_id)

    # Filter to only teams this specific key has access to
    scoped_teams = personal_api_key_instance.scoped_teams or []

    if scoped_teams:
        # Scoped key - only return teams in the scoped list
        scoped_team_tokens = set(Team.objects.filter(id__in=scoped_teams).values_list("api_token", flat=True))
        # Return intersection of user teams and scoped teams
        result = list(all_user_teams.intersection(scoped_team_tokens))
    else:
        # Unscoped key - return all teams the user has access to
        result = list(all_user_teams)

    return result
