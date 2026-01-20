"""
Flag Definitions HyperCache for SDK local evaluation.

This module provides HyperCaches that store feature flag definitions for SDKs to use
in local evaluation. Unlike the flags_cache.py which provides raw flag data for the
Rust feature-flags service, this provides rich data including cohort definitions and
group type mappings.

Two cache variants are provided:
- flags_hypercache: Includes full cohort definitions for smart clients
- flags_without_cohorts_hypercache: Cohort filters transformed to properties for simple clients

Cache Key Pattern:
- Uses api_token as the key (token-based cache)
- Stored in both Redis and S3 via HyperCache

Dual-Write Behavior:
- Writes to both shared cache (Django reads) and dedicated cache (Rust service reads)
- Django reads from shared cache only
- Dedicated cache writes are best-effort (failures logged but don't abort operation)

Configuration:
- Redis TTL: 7 days (configurable via FLAGS_CACHE_TTL env var)
- Miss TTL: 1 day (configurable via FLAGS_CACHE_MISS_TTL env var)
"""

import json
from collections import defaultdict
from collections.abc import Generator
from typing import Any, Union, cast

from django.conf import settings
from django.core.cache import caches
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog
from posthoganalytics import capture_exception

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feature_flag.feature_flag import FeatureFlagEvaluationTag
from posthog.models.feature_flag.types import FlagFilters, FlagProperty, PropertyFilterType
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.surveys.survey import Survey
from posthog.models.tag import Tag
from posthog.models.team import Team
from posthog.person_db_router import PERSONS_DB_FOR_READ
from posthog.storage.hypercache import HyperCache
from posthog.storage.hypercache_manager import HyperCacheManagementConfig, UpdateFn

logger = structlog.get_logger(__name__)


# Sorted set keys for tracking cache expirations
FLAG_DEFINITIONS_CACHE_EXPIRY_SORTED_SET = "flag_definitions_cache_expiry"
FLAG_DEFINITIONS_NO_COHORTS_CACHE_EXPIRY_SORTED_SET = "flag_definitions_no_cohorts_cache_expiry"


def _get_properties_from_filters(
    filters: Union[dict, FlagFilters], property_type: str | None = None
) -> Generator[FlagProperty, None, None]:
    """
    Extract properties from filters by iterating through groups.

    Args:
        filters: The filters dictionary containing groups
        property_type: Optional filter by property type (e.g., 'flag', 'cohort')

    Yields:
        Property dictionaries matching the criteria
    """
    for group in filters.get("groups", []):
        for prop in group.get("properties", []):
            if property_type is None or prop.get("type") == property_type:
                yield prop


def _get_flag_properties_from_filters(filters: Union[dict, FlagFilters]) -> Generator[FlagProperty, None, None]:
    """Extract flag properties from filters."""
    return _get_properties_from_filters(filters, PropertyFilterType.FLAG)


def _resolve_flag_dependency_key(flag_prop: FlagProperty, flag_id_to_key: dict[str, str]) -> str:
    """
    Convert flag property reference to flag key.
    Handles both flag IDs and flag keys as references.
    """
    flag_reference = flag_prop.get("key", "")
    return flag_id_to_key.get(flag_reference, flag_reference)


def _build_flag_id_to_key_mapping(flags) -> dict[str, str]:
    """Build mapping from flag ID to flag key for dependency transformation."""
    return {str(flag.id): flag.key for flag in flags}


class _DependencyChainBuilder:
    """
    Internal class for building flag dependency chains using topological sorting.

    Encapsulates the complex DFS logic and state management needed for dependency chain
    computation while providing memoization for performance.
    """

    def __init__(self, all_flags: dict[str, Any]):
        self.all_flags = all_flags
        self.memo: dict[str, list[str]] = {}

    def build_chain(self, flag_key: str) -> list[str]:
        """
        Build the dependency chain for a single flag using topological sorting.
        Returns a list of flag keys in the order they should be evaluated.

        Handles circular dependencies by detecting cycles and logging warnings.
        When a cycle is detected, returns an empty array since the flag cannot be safely evaluated.
        """
        if flag_key in self.memo:
            return self.memo[flag_key]

        if self._has_self_dependency(flag_key):
            logger.warning(
                "Self-dependency detected in feature flag",
                extra={"flag_key": flag_key},
            )
            self.memo[flag_key] = []
            return []

        # Build the chain using DFS
        visited: set[str] = set()
        temp_visited: set[str] = set()
        chain: list[str] = []

        if not self._dfs(flag_key, visited, temp_visited, chain):
            logger.warning(
                "Flag cannot be evaluated due to circular dependencies or missing dependencies",
                extra={"flag_key": flag_key},
            )
            self.memo[flag_key] = []
            return []

        self.memo[flag_key] = chain
        return chain

    def _has_self_dependency(self, flag_key: str) -> bool:
        """Check if a flag has a direct self-dependency."""
        flag_data = self.all_flags.get(flag_key)
        if not flag_data:
            return False

        filters = flag_data.get("filters", {})
        for flag_prop in _get_flag_properties_from_filters(filters):
            dep_flag_key = flag_prop["key"]  # Already normalized to key
            if dep_flag_key == flag_key:
                return True
        return False

    def _dfs(self, current_key: str, visited: set[str], temp_visited: set[str], chain: list[str]) -> bool:
        """
        Depth-first search to build dependency chain with cycle detection.

        Returns False if a cycle or missing dependency is detected, True otherwise.
        """
        if current_key in temp_visited:
            logger.warning(
                "Circular dependency detected in feature flags",
                extra={"circular_at": current_key},
            )
            return False

        if current_key in visited:
            return True

        temp_visited.add(current_key)

        if not self._validate_flag_exists(current_key):
            return False

        if not self._validate_all_dependencies_for_flag(current_key, visited, temp_visited, chain):
            return False

        temp_visited.remove(current_key)
        visited.add(current_key)
        chain.append(current_key)
        return True

    def _validate_flag_exists(self, flag_key: str) -> bool:
        """Validate that a flag exists in the flags collection."""
        if flag_key not in self.all_flags:
            logger.warning(
                "Attempting to build dependency chain for non-existent flag",
                extra={"flag_key": flag_key},
            )
            return False
        return True

    def _validate_all_dependencies_for_flag(
        self, current_key: str, visited: set[str], temp_visited: set[str], chain: list[str]
    ) -> bool:
        """Validates all dependencies of the current flag."""
        current_flag = self.all_flags.get(current_key)
        if not current_flag:
            return False

        filters = current_flag.get("filters", {})
        for flag_prop in _get_flag_properties_from_filters(filters):
            dep_flag_key = flag_prop["key"]  # Already normalized to key
            if dep_flag_key != current_key:  # Avoid self-dependency
                if not self._validate_dependency(dep_flag_key, current_key, visited, temp_visited, chain):
                    return False
        return True

    def _validate_dependency(
        self, dep_flag_key: str, current_key: str, visited: set[str], temp_visited: set[str], chain: list[str]
    ) -> bool:
        """Validates the dependency exists and recursively checks for cycles"""
        # Validate the dependency exists
        if dep_flag_key not in self.all_flags:
            logger.warning(
                "Flag dependency references non-existent flag",
                extra={"flag": current_key, "missing_dependency": dep_flag_key},
            )
            return False

        # Recursively process the dependency
        if not self._dfs(dep_flag_key, visited, temp_visited, chain):
            return False

        return True


def _normalize_and_collect_dependency_target_keys(
    flags_data: list[dict[str, Any]], flag_id_to_key: dict[str, str]
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Normalize flag properties and collect dependency target keys.

    Args:
        flags_data: List of flag data dictionaries to process
        flag_id_to_key: Mapping from flag IDs to flag keys

    Returns:
        tuple: (normalized_flags_data, unique_dependency_target_keys)
    """
    unique_dependencies = set()

    for flag_data in flags_data:
        filters = flag_data.get("filters", {})
        for flag_prop in _get_flag_properties_from_filters(filters):
            # Transform flag ID to flag key
            flag_key = _resolve_flag_dependency_key(flag_prop, flag_id_to_key)
            flag_prop["key"] = flag_key
            # Collect unique dependency at the same time
            unique_dependencies.add(flag_key)

    return flags_data, unique_dependencies


def _build_all_dependency_chains(
    flags_data: list[dict[str, Any]], unique_dependencies: set[str]
) -> list[dict[str, Any]]:
    """
    Final pass: Build dependency chains for all flag properties using pre-collected dependencies.
    Assumes flag IDs have already been normalized to keys and dependencies collected.
    Uses optimized batch processing with memoization to avoid rebuilding chains for shared dependencies.
    """
    if not unique_dependencies:
        return flags_data

    all_flags_by_key = {flag["key"]: flag for flag in flags_data}

    builder = _DependencyChainBuilder(all_flags_by_key)

    for dep_key in unique_dependencies:
        # This will populate the builder's cache
        builder.build_chain(dep_key)

    for flag_data in flags_data:
        filters = flag_data.get("filters", {})

        for flag_prop in _get_flag_properties_from_filters(filters):
            flag_key = flag_prop["key"]

            dependency_chain = builder.build_chain(flag_key)

            # The dependency chain represents the order in which flags should be evaluated
            # It includes the target flag and its dependencies in topological order
            # Always add the dependency_chain property, even if empty (for self-dependencies, missing dependencies, etc.)
            flag_prop["dependency_chain"] = dependency_chain

    return flags_data


def _transform_flag_property_dependencies(flags_data: list[dict[str, Any]], parsed_flags: list) -> list[dict[str, Any]]:
    """
    Transform flag properties in filter conditions to include dependency chains.
    Uses an optimized two-pass approach:
    1. Normalize flag IDs to keys and collect unique dependency target keys in single pass
    2. Build dependency chains for collected dependency targets using batch processing
    """
    flag_id_to_key = _build_flag_id_to_key_mapping(parsed_flags)

    flags_data, unique_dependencies = _normalize_and_collect_dependency_target_keys(flags_data, flag_id_to_key)

    flags_data = _build_all_dependency_chains(flags_data, unique_dependencies)

    return flags_data


def _apply_flag_dependency_transformation(response_data: dict[str, Any], parsed_flags: list) -> dict[str, Any]:
    """
    Apply flag dependency transformation to response data.

    This method transforms flag properties in filter conditions to include dependency chains,
    enabling simple client-side evaluation without complex graph construction.

    Args:
        response_data: The response data containing flags to transform
        parsed_flags: The original parsed feature flags for ID-to-key mapping

    Returns:
        New response data dictionary with transformed flags
    """
    try:
        flags_list = cast(list[dict[str, Any]], response_data["flags"])
        transformed_flags = _transform_flag_property_dependencies(flags_list, parsed_flags)

        logger.info("Flag dependency transformation completed")
        return {**response_data, "flags": transformed_flags}
    except Exception as e:
        logger.warning(
            "Flag dependency transformation failed, proceeding without transformation",
            extra={"error": str(e)},
        )
        return response_data


DATABASE_FOR_LOCAL_EVALUATION = (
    "default"
    if ("local_evaluation" not in settings.READ_REPLICA_OPT_IN or "replica" not in settings.DATABASES)  # noqa: F821
    else "replica"
)

# Use centralized database routing constant
READ_ONLY_DATABASE_FOR_PERSONS = PERSONS_DB_FOR_READ


def _get_flags_response_for_local_evaluation_batch(
    teams: list[Team], include_cohorts: bool
) -> dict[int, dict[str, Any]]:
    """
    Batch load flag definitions for multiple teams in optimized queries.

    Reduces N+1 queries by loading data for all teams in bulk:
    - All survey flag IDs in one query
    - All feature flags in one query
    - All cohorts in one query (grouped by project_id)
    - All group type mappings in one query

    Args:
        teams: List of Team objects to load flag definitions for
        include_cohorts: Whether to include full cohort definitions

    Returns:
        Dict mapping team_id to flag definitions response
    """
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    if not teams:
        return {}

    team_ids = [team.id for team in teams]
    project_ids = list({team.project_id for team in teams})

    # 1. Batch load all survey flag IDs for all teams (one query)
    survey_flag_ids_by_team: dict[int, set[int]] = defaultdict(set)
    survey_rows = (
        Survey.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(team_id__in=team_ids)
        .values_list(
            "team_id",
            "targeting_flag_id",
            "internal_targeting_flag_id",
            "internal_response_sampling_flag_id",
        )
    )
    for team_id, targeting, internal_targeting, sampling in survey_rows:
        for flag_id in (targeting, internal_targeting, sampling):
            if flag_id is not None:
                survey_flag_ids_by_team[team_id].add(flag_id)

    # 2. Batch load all feature flags for all teams (one query)
    all_survey_flag_ids = set()
    for ids in survey_flag_ids_by_team.values():
        all_survey_flag_ids.update(ids)

    all_flags = list(
        FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(
            ~Q(is_remote_configuration=True),
            team_id__in=team_ids,
            deleted=False,
        )
        .exclude(id__in=all_survey_flag_ids)
    )

    flags_by_team: dict[int, list[FeatureFlag]] = defaultdict(list)
    for flag in all_flags:
        flags_by_team[flag.team_id].append(flag)

    # 3. Batch load all cohorts for all project_ids (one query)
    cohorts_by_project: dict[int, dict[int, Cohort]] = defaultdict(dict)
    all_cohorts = Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
        team__project_id__in=project_ids, deleted=False
    )
    for cohort in all_cohorts:
        cohorts_by_project[cohort.team.project_id][cohort.pk] = cohort

    # 4. Batch load all group type mappings for all project_ids (one query)
    group_mappings_by_project: dict[int, dict[str, str]] = defaultdict(dict)
    all_mappings = GroupTypeMapping.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
        project_id__in=project_ids
    )
    for mapping in all_mappings:
        group_mappings_by_project[mapping.project_id][str(mapping.group_type_index)] = mapping.group_type

    # 5. Process each team's data using pre-loaded data
    result: dict[int, dict[str, Any]] = {}
    for team in teams:
        try:
            team_flags = flags_by_team.get(team.id, [])
            seen_cohorts_cache: dict[int, CohortOrEmpty] = cast(
                dict[int, CohortOrEmpty], cohorts_by_project.get(team.project_id, {})
            )
            group_type_mapping = group_mappings_by_project.get(team.project_id, {})

            cohorts: dict[str, dict] = {}

            # Process each flag with pre-loaded cohorts
            for feature_flag in team_flags:
                try:
                    filters = feature_flag.get_filters()

                    # Get cohort IDs using pre-loaded cache
                    cohort_ids = feature_flag.get_cohort_ids(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    )

                    # Transform cohort filters if needed
                    if not include_cohorts and len(cohort_ids) == 1:
                        feature_flag.filters = {
                            **filters,
                            "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                                seen_cohorts_cache=seen_cohorts_cache,
                            ),
                        }
                    else:
                        feature_flag.filters = filters

                    # Build cohorts dict when include_cohorts is True
                    if include_cohorts:
                        for cohort_id in cohort_ids:
                            if str(cohort_id) not in cohorts:
                                cohort = seen_cohorts_cache.get(cohort_id)
                                if cohort and not cohort.is_static:
                                    try:
                                        cohorts[str(cohort.pk)] = cohort.properties.to_dict()
                                    except Exception:
                                        logger.error(
                                            "Error processing cohort properties in batch",
                                            extra={"cohort_id": cohort_id},
                                            exc_info=True,
                                        )
                except Exception:
                    logger.error(
                        "Error processing feature flag in batch",
                        extra={"flag_id": feature_flag.pk},
                        exc_info=True,
                    )
                    continue

            response_data = {
                "flags": [MinimalFeatureFlagSerializer(flag, context={}).data for flag in team_flags],
                "group_type_mapping": group_type_mapping,
                "cohorts": cohorts,
            }

            result[team.id] = _apply_flag_dependency_transformation(response_data, team_flags)

        except Exception as e:
            logger.warning(
                "Failed to load flag definitions for team in batch",
                team_id=team.id,
                include_cohorts=include_cohorts,
                error=str(e),
            )
            continue

    return result


# HyperCache instances for flag definitions
# Note: No cache_alias - reads from shared cache (Django reads from shared, Rust service reads from dedicated)
# Dual-write to dedicated cache is handled in update_flag_definitions_cache()
flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_with_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=True),
    token_based=True,
    cache_ttl=settings.FLAGS_CACHE_TTL,
    cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
    batch_load_fn=lambda teams: _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=True),
    enable_etag=True,
    expiry_sorted_set_key=FLAG_DEFINITIONS_CACHE_EXPIRY_SORTED_SET,
)

flags_without_cohorts_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_without_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=False),
    token_based=True,
    cache_ttl=settings.FLAGS_CACHE_TTL,
    cache_miss_ttl=settings.FLAGS_CACHE_MISS_TTL,
    batch_load_fn=lambda teams: _get_flags_response_for_local_evaluation_batch(teams, include_cohorts=False),
    enable_etag=True,
    expiry_sorted_set_key=FLAG_DEFINITIONS_NO_COHORTS_CACHE_EXPIRY_SORTED_SET,
)


def get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict | None:
    return (
        flags_hypercache.get_from_cache(team)
        if include_cohorts
        else flags_without_cohorts_hypercache.get_from_cache(team)
    )


def get_flags_response_if_none_match(
    team: Team, include_cohorts: bool, client_etag: str | None
) -> tuple[dict | None, str | None, bool]:
    """
    Get flags response with ETag support for HTTP 304 responses.

    Returns: (data, etag, modified)
    - If client_etag matches current: (None, current_etag, False) - 304 case
    - Otherwise: (data, current_etag, True) - 200 case with full data
    """
    hypercache = flags_hypercache if include_cohorts else flags_without_cohorts_hypercache
    return hypercache.get_if_none_match(team, client_etag)


def _write_to_dedicated_cache(cache_key: str, json_data: str, etag_key: str | None, etag: str | None, timeout: int):
    """
    Write flag definitions to the dedicated cache (best-effort).

    This is called after writing to the shared cache to ensure the Rust service
    also has access to the data.

    Args:
        cache_key: The cache key to write to
        json_data: JSON-serialized data to write
        etag_key: Optional ETag key for HTTP 304 support
        etag: Optional ETag value
        timeout: Cache TTL in seconds
    """
    if FLAGS_DEDICATED_CACHE_ALIAS not in settings.CACHES:
        return

    try:
        dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
        if etag_key and etag:
            # Write data and ETag together for atomicity
            dedicated_cache.set_many({cache_key: json_data, etag_key: etag}, timeout=timeout)
        else:
            dedicated_cache.set(cache_key, json_data, timeout=timeout)
    except Exception as e:
        logger.warning(
            "Dedicated cache write failed for flag definitions",
            extra={"cache_key": cache_key},
            exc_info=True,
        )
        capture_exception(e)


def update_flag_definitions_cache(team_or_id: Team | int, ttl: int | None = None) -> bool:
    """
    Update the flag definitions cache for a team with dual-write support.

    Writes to both shared cache (Django reads) and dedicated cache (Rust service reads).
    The shared cache write is mandatory; dedicated cache write is best-effort.

    This updates both cache variants (with and without cohorts).

    Args:
        team_or_id: Team object or team ID
        ttl: Optional custom TTL in seconds (defaults to FLAGS_CACHE_TTL)

    Returns:
        True if both cache updates succeeded, False otherwise
    """
    # Resolve team if ID was passed
    if isinstance(team_or_id, int):
        try:
            team = Team.objects.get(id=team_or_id)
        except Team.DoesNotExist:
            logger.warning("Team not found for flag definitions cache update", team_id=team_or_id)
            return False
    else:
        team = team_or_id

    timeout = ttl if ttl is not None else settings.FLAGS_CACHE_TTL

    success = True

    # Update both cache variants
    for hypercache, include_cohorts in [
        (flags_hypercache, True),
        (flags_without_cohorts_hypercache, False),
    ]:
        try:
            # Load data
            data = _get_flags_response_for_local_evaluation(team, include_cohorts)

            # Write to shared cache via HyperCache (also writes to S3 and tracks expiry)
            hypercache.set_cache_value(team, data, ttl=timeout)

            # Dual-write to dedicated cache
            cache_key = hypercache.get_cache_key(team)
            json_data = json.dumps(data, sort_keys=True)

            # Compute ETag if enabled
            etag_key = None
            etag = None
            if hypercache.enable_etag:
                etag_key = hypercache.get_etag_key(team)
                etag = hypercache._compute_etag(json_data)

            _write_to_dedicated_cache(cache_key, json_data, etag_key, etag, timeout)

        except Exception as e:
            logger.exception(
                "Failed to update flag definitions cache",
                team_id=team.id,
                include_cohorts=include_cohorts,
                error=str(e),
            )
            capture_exception(e)
            success = False

    return success


def update_flag_caches(team: Team):
    """
    Legacy function for signal-driven cache updates.

    This is called by Django signals when flags/cohorts change.
    Delegates to update_flag_definitions_cache for dual-write support.
    """
    update_flag_definitions_cache(team)


def clear_flag_definition_caches(team: Team, kinds: list[str] | None = None):
    """
    Clear the flag definitions cache for a team.

    Clears from both shared and dedicated caches, and removes from expiry tracking.

    Args:
        team: Team object
        kinds: Optional list of cache kinds to clear ("redis", "s3")
    """
    from posthog.redis import get_client

    # Clear from shared cache (and S3 if requested)
    flags_hypercache.clear_cache(team, kinds=kinds)
    flags_without_cohorts_hypercache.clear_cache(team, kinds=kinds)

    # Clear from dedicated cache
    if FLAGS_DEDICATED_CACHE_ALIAS in settings.CACHES:
        try:
            dedicated_cache = caches[FLAGS_DEDICATED_CACHE_ALIAS]
            for hypercache in [flags_hypercache, flags_without_cohorts_hypercache]:
                cache_key = hypercache.get_cache_key(team)
                etag_key = hypercache.get_etag_key(team)
                dedicated_cache.delete(cache_key)
                dedicated_cache.delete(etag_key)
        except Exception as e:
            logger.warning(
                "Failed to clear dedicated cache for flag definitions",
                team_id=team.id,
                error=str(e),
            )

    # Remove from expiry tracking sorted sets
    try:
        redis_client = get_client(settings.REDIS_URL)
        identifier = team.api_token  # Token-based cache
        redis_client.zrem(FLAG_DEFINITIONS_CACHE_EXPIRY_SORTED_SET, str(identifier))
        redis_client.zrem(FLAG_DEFINITIONS_NO_COHORTS_CACHE_EXPIRY_SORTED_SET, str(identifier))
    except Exception as e:
        logger.warning(
            "Failed to remove from flag definitions expiry tracking",
            team_id=team.id,
            error=str(e),
        )


def clear_flag_caches(team: Team, kinds: list[str] | None = None):
    """
    Legacy function for clearing flag caches.

    Delegates to clear_flag_definition_caches for proper cleanup.
    """
    clear_flag_definition_caches(team, kinds=kinds)


def _get_flags_for_local_evaluation(team: Team, include_cohorts: bool = True) -> tuple[list[FeatureFlag], dict]:
    """
    Get all feature flags for a team with conditional cohort handling for local evaluation.

    This method supports two different client integration patterns:

    Args:
        team: The team to get feature flags for.
        include_cohorts: Controls cohort handling strategy for client compatibility.

    Returns:
        tuple[list[FeatureFlag], dict]: (flags, cohorts_dict)

    Behavior based on include_cohorts:

    When include_cohorts=True (for smart clients):
        - Flag filters are kept unchanged (cohort references preserved)
        - Returns cohorts dict with cohort definitions for client-side evaluation
        - Client must evaluate cohort membership locally using provided cohort criteria

    When include_cohorts=False (for simple clients):
        - Flag filters are transformed (simple cohorts expanded to person properties)
        - Returns empty cohorts dict
        - Client only needs to evaluate simplified property-based filters
    """

    # Exclude survey-linked flags from local evaluation. See GitHub issue #43631.
    survey_flag_ids = Survey.get_internal_flag_ids(
        team_id=team.id,
        using=DATABASE_FOR_LOCAL_EVALUATION,
    )

    feature_flags = (
        FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(
            ~Q(is_remote_configuration=True),
            team_id=team.id,
            deleted=False,
        )
        .exclude(id__in=survey_flag_ids)
    )

    cohorts = {}
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {}

    try:
        seen_cohorts_cache = {
            cohort.pk: cohort
            for cohort in Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
                team__project_id=team.project_id, deleted=False
            )
        }
    except Exception:
        logger.error("Error prefetching cohorts", exc_info=True)

    for feature_flag in feature_flags:
        try:
            filters = feature_flag.get_filters()

            # Capture cohort_ids BEFORE transformation to avoid losing cohort references
            cohort_ids = feature_flag.get_cohort_ids(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            )

            # transform cohort filters to be evaluated locally, but only if include_cohorts is false
            if not include_cohorts and len(cohort_ids) == 1:
                feature_flag.filters = {
                    **filters,
                    "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                        using_database=DATABASE_FOR_LOCAL_EVALUATION,
                        seen_cohorts_cache=seen_cohorts_cache,
                    ),
                }
            else:
                feature_flag.filters = filters

            # Only build cohorts when include_cohorts is True (matching send_cohorts behavior)
            if include_cohorts:
                for id in cohort_ids:
                    # don't duplicate queries for already added cohorts
                    if id not in cohorts:
                        if id in seen_cohorts_cache:
                            cohort = seen_cohorts_cache[id]
                        else:
                            cohort = (
                                Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
                                .filter(id=id, team__project_id=team.project_id, deleted=False)
                                .first()
                            )
                            seen_cohorts_cache[id] = cohort or ""

                        if cohort and not cohort.is_static:
                            try:
                                cohorts[str(cohort.pk)] = cohort.properties.to_dict()
                            except Exception:
                                logger.error(
                                    "Error processing cohort properties",
                                    extra={"cohort_id": id},
                                    exc_info=True,
                                )
                                continue

        except Exception:
            logger.error("Error processing feature flag", extra={"flag_id": feature_flag.pk}, exc_info=True)
            continue

    return feature_flags, cohorts


def _get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict[str, Any]:
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    flags, cohorts = _get_flags_for_local_evaluation(team, include_cohorts)

    response_data = {
        "flags": [MinimalFeatureFlagSerializer(feature_flag, context={}).data for feature_flag in flags],
        "group_type_mapping": {
            str(row.group_type_index): row.group_type
            for row in GroupTypeMapping.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
                project_id=team.project_id
            )
        },
        "cohorts": cohorts,
    }

    # Transform flag dependencies for simplified client-side evaluation
    return _apply_flag_dependency_transformation(response_data, flags)


def verify_team_flag_definitions(
    team: Team,
    db_batch_data: dict | None = None,
    cache_batch_data: dict | None = None,
    include_cohorts: bool = True,
    verbose: bool = False,
) -> dict:
    """
    Verify a team's flag definitions cache against the database.

    Args:
        team: Team to verify
        db_batch_data: Pre-loaded DB data from batch_load_fn (keyed by team.id)
        cache_batch_data: Pre-loaded cache data from batch_get_from_cache (keyed by team.id)
        include_cohorts: Which cache variant to verify (True for with-cohorts, False for without)
        verbose: If True, include detailed diffs

    Returns:
        Dict with 'status' ("match", "miss", "mismatch") and 'issue' type.
    """
    hypercache = flags_hypercache if include_cohorts else flags_without_cohorts_hypercache

    # Get cached data - use pre-loaded batch data if available
    if cache_batch_data and team.id in cache_batch_data:
        cached_data, source = cache_batch_data[team.id]
    else:
        cached_data, source = hypercache.get_from_cache_with_source(team)

    # Get flag definitions from database
    if db_batch_data and team.id in db_batch_data:
        db_data = db_batch_data[team.id]
    else:
        db_data = _get_flags_response_for_local_evaluation(team, include_cohorts)

    db_flags = db_data.get("flags", []) if isinstance(db_data, dict) else []

    # Cache miss (source="db" or "miss" means data was not found in cache)
    if source in ("db", "miss"):
        return {
            "status": "miss",
            "issue": "CACHE_MISS",
            "details": f"No cache entry found (team has {len(db_flags)} flags in DB)",
        }

    # Extract cached flags
    cached_flags = cached_data.get("flags", []) if cached_data else []

    # Compare flags by key (flag definitions use key as primary identifier)
    db_flags_by_key = {flag.get("key"): flag for flag in db_flags}
    cached_flags_by_key = {flag.get("key"): flag for flag in cached_flags}

    diffs = []

    # Find missing flags (in DB but not in cache)
    for flag_key in db_flags_by_key:
        if flag_key not in cached_flags_by_key:
            diffs.append(
                {
                    "type": "MISSING_IN_CACHE",
                    "flag_key": flag_key,
                }
            )

    # Find stale flags (in cache but not in DB)
    for flag_key in cached_flags_by_key:
        if flag_key not in db_flags_by_key:
            diffs.append(
                {
                    "type": "STALE_IN_CACHE",
                    "flag_key": flag_key,
                }
            )

    # Compare field values for flags that exist in both
    for flag_key in db_flags_by_key:
        if flag_key in cached_flags_by_key:
            db_flag = db_flags_by_key[flag_key]
            cached_flag = cached_flags_by_key[flag_key]
            if db_flag != cached_flag:
                field_diffs = _compare_flag_definition_fields(db_flag, cached_flag)
                diff: dict = {
                    "type": "FIELD_MISMATCH",
                    "flag_key": flag_key,
                    "diff_fields": [f["field"] for f in field_diffs],
                }
                if verbose:
                    diff["field_diffs"] = field_diffs
                diffs.append(diff)

    # Also compare cohorts and group_type_mapping
    if cached_data and db_data:
        if cached_data.get("cohorts") != db_data.get("cohorts"):
            diffs.append({"type": "COHORTS_MISMATCH", "flag_key": "cohorts"})
        if cached_data.get("group_type_mapping") != db_data.get("group_type_mapping"):
            diffs.append({"type": "GROUP_TYPE_MAPPING_MISMATCH", "flag_key": "group_type_mapping"})

    if not diffs:
        return {"status": "match", "issue": "", "details": ""}

    # Summarize diffs
    missing_count = sum(1 for d in diffs if d.get("type") == "MISSING_IN_CACHE")
    stale_count = sum(1 for d in diffs if d.get("type") == "STALE_IN_CACHE")
    mismatch_count = sum(1 for d in diffs if d.get("type") == "FIELD_MISMATCH")

    summary_parts = []
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")
    if stale_count > 0:
        summary_parts.append(f"{stale_count} stale")
    if mismatch_count > 0:
        summary_parts.append(f"{mismatch_count} mismatched")

    result: dict = {
        "status": "mismatch",
        "issue": "DATA_MISMATCH",
        "details": f"{', '.join(summary_parts)} flags" if summary_parts else "unknown differences",
    }

    if verbose:
        result["diffs"] = diffs

    return result


def _compare_flag_definition_fields(db_flag: dict, cached_flag: dict) -> list[dict]:
    """Compare field values between DB and cached versions of a flag."""
    field_diffs = []
    all_keys = set(db_flag.keys()) | set(cached_flag.keys())

    for key in all_keys:
        db_val = db_flag.get(key)
        cached_val = cached_flag.get(key)

        if db_val != cached_val:
            field_diffs.append({"field": key, "db_value": db_val, "cached_value": cached_val})

    return field_diffs


# HyperCache management configs for warming/verification
# Note: We have two separate configs, one for each cache variant
FLAG_DEFINITIONS_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flags_hypercache,
    update_fn=cast(UpdateFn, update_flag_definitions_cache),
    cache_name="flag_definitions",
)

FLAG_DEFINITIONS_NO_COHORTS_HYPERCACHE_MANAGEMENT_CONFIG = HyperCacheManagementConfig(
    hypercache=flags_without_cohorts_hypercache,
    update_fn=cast(UpdateFn, update_flag_definitions_cache),
    cache_name="flag_definitions_no_cohorts",
)


# NOTE: All models that affect feature flag evaluation should have a signal to update the cache
# GroupTypeMapping excluded as it's primarily managed by Node.js plugin-server


@receiver(post_save, sender=FeatureFlag)
@receiver(post_delete, sender=FeatureFlag)
def feature_flag_changed(sender, instance: "FeatureFlag", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    # Defer task execution until after the transaction commits
    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=Cohort)
@receiver(post_delete, sender=Cohort)
def cohort_changed(sender, instance: "Cohort", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    transaction.on_commit(lambda: update_team_flags_cache.delay(instance.team_id))


@receiver(post_save, sender=FeatureFlagEvaluationTag)
@receiver(post_delete, sender=FeatureFlagEvaluationTag)
def evaluation_tag_changed(sender, instance: "FeatureFlagEvaluationTag", **kwargs):
    from posthog.tasks.feature_flags import update_team_flags_cache

    team_id = instance.feature_flag.team_id
    transaction.on_commit(lambda: update_team_flags_cache.delay(team_id))


@receiver(post_save, sender=Tag)
def tag_changed(sender, instance: "Tag", created: bool, **kwargs):
    """
    Invalidate flags cache when a tag is renamed.

    Tag names are cached in evaluation_tags, so if a tag used by any flag
    is renamed, we need to refresh those teams' caches.
    """
    if created:
        return  # New tags can't be used by any flags yet

    # In practice, update_fields is rarely specified when saving Tags,
    # but this check follows the pattern used elsewhere in the codebase.
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "name" not in update_fields:
        return

    from posthog.tasks.feature_flags import update_team_flags_cache

    for team_id in FeatureFlagEvaluationTag.get_team_ids_using_tag(instance):
        # Capture team_id in closure to avoid late binding issues
        transaction.on_commit(lambda tid=team_id: update_team_flags_cache.delay(tid))  # type: ignore[misc]
