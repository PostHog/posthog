from collections.abc import Generator
from typing import Any, Union, cast

from django.conf import settings
from django.db import connections, transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

import structlog

from posthog.models.cohort.cohort import Cohort, CohortOrEmpty
from posthog.models.feature_flag import FeatureFlag
from posthog.models.feature_flag.types import FlagFilters, FlagProperty, PropertyFilterType
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team import Team
from posthog.storage.hypercache import HyperCache

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

# For person-related models (GroupTypeMapping), use persons DB if configured
# It'll use `replica` until we set the PERSONS_DB_WRITER_URL env var
READ_ONLY_DATABASE_FOR_PERSONS = (
    "persons_db_reader"
    if "persons_db_reader" in connections
    else "replica"
    if "replica" in connections and "local_evaluation" in settings.READ_REPLICA_OPT_IN
    else "default"
)  # Fallback if persons DB not configured

flags_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_with_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=True),
)

flags_without_cohorts_hypercache = HyperCache(
    namespace="feature_flags",
    value="flags_without_cohorts.json",
    load_fn=lambda key: _get_flags_response_for_local_evaluation(HyperCache.team_from_key(key), include_cohorts=False),
)


def get_flags_response_for_local_evaluation(team: Team, include_cohorts: bool) -> dict | None:
    return (
        flags_hypercache.get_from_cache(team)
        if include_cohorts
        else flags_without_cohorts_hypercache.get_from_cache(team)
    )


def update_flag_caches(team: Team):
    flags_hypercache.update_cache(team)
    flags_without_cohorts_hypercache.update_cache(team)


def clear_flag_caches(team: Team, kinds: list[str] | None = None):
    flags_hypercache.clear_cache(team, kinds=kinds)
    flags_without_cohorts_hypercache.clear_cache(team, kinds=kinds)


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

    feature_flags = FeatureFlag.objects.db_manager(DATABASE_FOR_LOCAL_EVALUATION).filter(
        ~Q(is_remote_configuration=True),
        team__project_id=team.project_id,
        deleted=False,
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
