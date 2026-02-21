import time
from collections.abc import Generator
from typing import Any, Union, cast

from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog
from posthoganalytics import capture_exception

from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feature_flag.feature_flag import FeatureFlagEvaluationTag
from posthog.models.feature_flag.types import FlagFilters, FlagProperty, PropertyFilterType
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.surveys.survey import Survey
from posthog.models.tag import Tag
from posthog.models.team import Team
from posthog.person_db_router import PERSONS_DB_FOR_READ
from posthog.storage.hypercache import HyperCache, emit_cache_sync_metrics

logger = structlog.get_logger(__name__)


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


def _transform_flag_property_dependencies(
    flags_data: list[dict[str, Any]], flag_id_to_key: dict[str, str]
) -> list[dict[str, Any]]:
    """
    Transform flag properties in filter conditions to include dependency chains.
    Uses an optimized two-pass approach:
    1. Normalize flag IDs to keys and collect unique dependency target keys in single pass
    2. Build dependency chains for collected dependency targets using batch processing

    Args:
        flags_data: List of serialized flag dictionaries to transform
        flag_id_to_key: Mapping from flag ID (as string) to flag key
    """
    flags_data, unique_dependencies = _normalize_and_collect_dependency_target_keys(flags_data, flag_id_to_key)

    flags_data = _build_all_dependency_chains(flags_data, unique_dependencies)

    return flags_data


def _apply_flag_dependency_transformation(
    response_data: dict[str, Any], flag_id_to_key: dict[str, str]
) -> dict[str, Any]:
    """
    Apply flag dependency transformation to response data.

    This method transforms flag properties in filter conditions to include dependency chains,
    enabling simple client-side evaluation without complex graph construction.

    Args:
        response_data: The response data containing flags to transform
        flag_id_to_key: Mapping from flag ID (as string) to flag key

    Returns:
        New response data dictionary with transformed flags
    """
    try:
        flags_list = cast(list[dict[str, Any]], response_data["flags"])
        transformed_flags = _transform_flag_property_dependencies(flags_list, flag_id_to_key)

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

flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_with_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=True),
    enable_etag=True,
)

flags_without_cohorts_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_without_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=False),
    enable_etag=True,
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


def update_flag_caches(team: Team):
    """Update both flag cache variants."""
    logger.info(f"Syncing feature_flags cache for team {team.id}")

    start_time = time.time()
    success = False
    size_with_cohorts: int | None = None
    size_without_cohorts: int | None = None
    try:
        with_cohorts = _get_flags_response_for_local_evaluation(team, include_cohorts=True)
        size_with_cohorts = flags_hypercache.set_cache_value(team, with_cohorts)

        without_cohorts = _get_flags_response_for_local_evaluation(team, include_cohorts=False)
        size_without_cohorts = flags_without_cohorts_hypercache.set_cache_value(team, without_cohorts)

        success = True
    except Exception as e:
        capture_exception(e)
        logger.exception(f"Failed to sync feature_flags cache for team {team.id}", exception=str(e))
    finally:
        duration = time.time() - start_time
        result = "success" if success else "failure"
        emit_cache_sync_metrics(
            result, "feature_flags", "flags_local_eval.json", duration=duration, increment_counter=False
        )
        emit_cache_sync_metrics(result, "feature_flags", "flags_with_cohorts.json", size=size_with_cohorts)
        emit_cache_sync_metrics(result, "feature_flags", "flags_without_cohorts.json", size=size_without_cohorts)


def clear_flag_caches(team: Team, kinds: list[str] | None = None):
    flags_hypercache.clear_cache(team, kinds=kinds)
    flags_without_cohorts_hypercache.clear_cache(team, kinds=kinds)


def _extract_cohort_ids_from_filters(filters: dict) -> set[int]:
    """
    Extract cohort IDs directly from flag filters without loading from DB.
    Only extracts direct references, not nested dependencies.
    """
    cohort_ids: set[int] = set()
    for prop in _get_properties_from_filters(filters, "cohort"):
        value = prop.get("value")
        # Skip list values to align with other cohort-processing code paths
        if value is None or isinstance(value, list):
            continue
        try:
            cohort_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return cohort_ids


def _load_cohorts_with_dependencies(
    direct_cohort_ids: set[int], project_id: int, using_database: str
) -> dict[int, CohortOrEmpty]:
    """
    Load cohorts and their dependencies in bulk queries.

    Performs iterative bulk loading to resolve nested cohort dependencies
    with minimal database queries (typically 1-2 iterations).
    """
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
    ids_to_load = direct_cohort_ids.copy()
    loaded_ids: set[int] = set()

    while ids_to_load:
        # Load cohorts in bulk with team prefetched to avoid N+1 queries
        # when get_all_cohort_dependencies accesses cohort.team.project_id
        new_cohorts = (
            Cohort.objects.db_manager(using_database)
            .filter(pk__in=ids_to_load, team__project_id=project_id, deleted=False)
            .select_related("team")
        )

        # Add loaded cohorts to cache
        for cohort in new_cohorts:
            seen_cohorts_cache[cohort.pk] = cohort
            loaded_ids.add(cohort.pk)

        # Mark missing cohorts as empty to avoid repeated lookups
        for cohort_id in ids_to_load:
            if cohort_id not in seen_cohorts_cache:
                seen_cohorts_cache[cohort_id] = ""
                loaded_ids.add(cohort_id)

        # Extract nested cohort IDs from newly loaded cohorts
        nested_ids: set[int] = set()
        for cohort_id in ids_to_load:
            cohort = seen_cohorts_cache.get(cohort_id)
            if isinstance(cohort, Cohort):
                for prop in cohort.properties.flat:
                    if prop.type == "cohort" and not isinstance(prop.value, list):
                        try:
                            nested_id = int(prop.value)
                            if nested_id not in loaded_ids:
                                nested_ids.add(nested_id)
                        except (ValueError, TypeError):
                            continue

        # Continue with nested IDs that haven't been loaded
        ids_to_load = nested_ids

    return seen_cohorts_cache


def _get_cohort_with_fallback(
    cohort_id: int, team: Team, seen_cohorts_cache: dict[int, CohortOrEmpty]
) -> CohortOrEmpty:
    """
    Get a cohort from cache, falling back to a database query if not found.

    Updates the cache with the result to avoid repeated queries.
    """
    if cohort_id in seen_cohorts_cache:
        return seen_cohorts_cache[cohort_id]

    logger.warning(
        "Cohort not in seen_cohorts_cache, performing fallback query",
        extra={"cohort_id": cohort_id, "team_id": team.id},
    )
    cohort = (
        Cohort.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(id=cohort_id, team__project_id=team.project_id, deleted=False)
        .first()
    )
    seen_cohorts_cache[cohort_id] = cohort or ""
    return seen_cohorts_cache[cohort_id]


def _add_cohort_to_dict(
    cohort_id: int,
    team: Team,
    seen_cohorts_cache: dict[int, CohortOrEmpty],
    cohorts_dict: dict[str, Any],
) -> None:
    """
    Add a cohort to the cohorts dict if it's valid and not already present.

    Handles skipping already-added cohorts, looking up cohorts with fallback,
    skipping static cohorts, and error handling for properties serialization.
    """
    if str(cohort_id) in cohorts_dict:
        return

    cohort = _get_cohort_with_fallback(cohort_id, team, seen_cohorts_cache)
    if cohort and not cohort.is_static:
        try:
            cohorts_dict[str(cohort.pk)] = cohort.properties.to_dict()
        except Exception:
            logger.error(
                "Error processing cohort properties",
                extra={"cohort_id": cohort_id},
                exc_info=True,
            )


def _get_transformed_filters_for_without_cohorts(
    feature_flag: FeatureFlag,
    original_filters: dict,
    cohort_ids: list[int],
    seen_cohorts_cache: dict[int, CohortOrEmpty],
) -> dict:
    """
    Get filters for without-cohorts response, transforming single-cohort filters.

    When a flag has exactly one cohort, transforms cohort filters to person
    properties for simpler client-side evaluation.
    """
    if len(cohort_ids) == 1:
        return {
            **original_filters,
            "groups": feature_flag.transform_cohort_filters_for_easy_evaluation(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            ),
        }
    return original_filters


def _get_base_flags_queryset(team: Team) -> QuerySet[FeatureFlag]:
    """
    Return the base queryset for feature flags, excluding survey-linked flags
    and encrypted remote configuration flags.
    """
    survey_flag_ids = Survey.get_internal_flag_ids(
        team_id=team.id,
        using=DATABASE_FOR_LOCAL_EVALUATION,
    )

    return (
        FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION)
        .filter(
            ~Q(is_remote_configuration=True, has_encrypted_payloads=True),
            team_id=team.id,
            deleted=False,
        )
        .exclude(id__in=survey_flag_ids)
    )


def _load_flags_and_cohorts_for_team(team: Team) -> tuple[list[FeatureFlag], dict[int, CohortOrEmpty]]:
    """
    Load feature flags and their cohort dependencies for a team.

    Handles:
    - Excluding survey-linked flags
    - Excluding remote configuration flags
    - Extracting cohort IDs from flag filters
    - Loading cohorts with nested dependencies

    Returns:
        tuple: (feature_flags, seen_cohorts_cache)
    """
    feature_flags = list(_get_base_flags_queryset(team))

    seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
    try:
        all_direct_cohort_ids: set[int] = set()
        for flag in feature_flags:
            all_direct_cohort_ids.update(_extract_cohort_ids_from_filters(flag.get_filters()))

        if all_direct_cohort_ids:
            seen_cohorts_cache = _load_cohorts_with_dependencies(
                all_direct_cohort_ids, team.project_id, DATABASE_FOR_LOCAL_EVALUATION
            )
    except Exception:
        logger.error("Error loading cohorts for flags", exc_info=True)

    return feature_flags, seen_cohorts_cache


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
    feature_flags, seen_cohorts_cache = _load_flags_and_cohorts_for_team(team)
    cohorts: dict[str, Any] = {}

    for feature_flag in feature_flags:
        try:
            filters = feature_flag.get_filters()

            # Capture cohort_ids BEFORE transformation to avoid losing cohort references
            cohort_ids = feature_flag.get_cohort_ids(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            )

            # Transform cohort filters for simple clients, or keep original filters
            if not include_cohorts:
                feature_flag.filters = _get_transformed_filters_for_without_cohorts(
                    feature_flag, filters, cohort_ids, seen_cohorts_cache
                )
            else:
                feature_flag.filters = filters

            # Only build cohorts when include_cohorts is True (matching send_cohorts behavior)
            if include_cohorts:
                for cohort_id in cohort_ids:
                    _add_cohort_to_dict(cohort_id, team, seen_cohorts_cache, cohorts)

        except Exception:
            logger.error("Error processing feature flag", extra={"flag_id": feature_flag.pk}, exc_info=True)
            continue

    return feature_flags, cohorts


def _get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict[str, Any]:
    """
    Build the local-evaluation response using streamed flag processing to reduce peak memory.

    Uses .iterator() to stream flags from the database rather than materializing
    all ORM objects with list(). This keeps peak memory close to the size of the
    final serialized response, since only one FeatureFlag instance is in memory at
    a time during processing. This matters for teams with many flags, where eager
    loading caused worker memory to spike well beyond the size of the output.
    """
    from posthog.api.feature_flag import MinimalFeatureFlagSerializer

    base_queryset = _get_base_flags_queryset(team)

    # Pass 1: collect cohort IDs from flag filters (lightweight, only loads filters column)
    all_direct_cohort_ids: set[int] = set()
    for flag in base_queryset.only("filters").iterator():
        all_direct_cohort_ids.update(_extract_cohort_ids_from_filters(flag.filters or {}))

    # Bulk load cohorts with nested dependencies
    seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
    if all_direct_cohort_ids:
        try:
            seen_cohorts_cache = _load_cohorts_with_dependencies(
                all_direct_cohort_ids, team.project_id, DATABASE_FOR_LOCAL_EVALUATION
            )
        except Exception:
            logger.error("Error loading cohorts for flags", exc_info=True)

    # Pass 2: stream flags, serialize each immediately
    flags_data: list[dict[str, Any]] = []
    cohorts: dict[str, Any] = {}
    flag_id_to_key: dict[str, str] = {}

    for feature_flag in base_queryset.iterator():
        try:
            filters = feature_flag.get_filters()

            cohort_ids = feature_flag.get_cohort_ids(
                using_database=DATABASE_FOR_LOCAL_EVALUATION,
                seen_cohorts_cache=seen_cohorts_cache,
            )

            if not include_cohorts:
                feature_flag.filters = _get_transformed_filters_for_without_cohorts(
                    feature_flag, filters, cohort_ids, seen_cohorts_cache
                )
            else:
                feature_flag.filters = filters

            flags_data.append(MinimalFeatureFlagSerializer(feature_flag, context={}).data)

            if include_cohorts:
                for cohort_id in cohort_ids:
                    _add_cohort_to_dict(cohort_id, team, seen_cohorts_cache, cohorts)

            flag_id_to_key[str(feature_flag.id)] = feature_flag.key

        except Exception:
            logger.error("Error processing feature flag", extra={"flag_id": feature_flag.pk}, exc_info=True)
            continue

    response_data = {
        "flags": flags_data,
        "group_type_mapping": {
            str(row.group_type_index): row.group_type
            for row in GroupTypeMapping.objects.db_manager(READ_ONLY_DATABASE_FOR_PERSONS).filter(
                project_id=team.project_id
            )
        },
        "cohorts": cohorts if include_cohorts else {},
    }

    return _apply_flag_dependency_transformation(response_data, flag_id_to_key)


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
