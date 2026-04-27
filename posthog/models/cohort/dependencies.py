from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

import posthoganalytics
from prometheus_client import Counter
from rest_framework.exceptions import ValidationError
from structlog import get_logger

from posthog.models.cohort.cohort import Cohort, CohortType, is_cohort_recalculation_only_save
from posthog.models.team.team import Team
from posthog.redis import get_client as get_redis_client

logger = get_logger(__name__)
DEPENDENCY_CACHE_TIMEOUT = 7 * 24 * 60 * 60  # 1 week
COHORT_BACKFILL_DEBOUNCE_SECONDS = 300  # 5 minutes
COHORT_BACKFILL_REDIS_TTL_SECONDS = 300  # matches countdown; task reads fresh state at execution time


# Prometheus metrics for cache hit/miss tracking
COHORT_DEPENDENCY_CACHE_COUNTER = Counter(
    "posthog_cohort_dependency_cache_requests_total",
    "Total number of cohort dependency cache requests",
    labelnames=["cache_type", "result"],
)


def _cohort_dependencies_key(cohort_id: int) -> str:
    return f"cohort:dependencies:{cohort_id}"


def _cohort_dependents_key(cohort_id: int) -> str:
    return f"cohort:dependents:{cohort_id}"


def extract_cohort_dependencies(cohort: Cohort) -> set[int]:
    """
    Extract cohort dependencies from the given cohort.
    """
    dependencies = set()
    if not cohort.deleted:
        try:
            for prop in cohort.properties.flat:
                if prop.type == "cohort" and isinstance(prop.value, int) and prop.value != cohort.id:
                    dependencies.add(prop.value)
        except ValidationError as e:
            COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="invalid").inc()
            logger.warning("Skipping cohort with invalid filters", cohort_id=cohort.id, error=str(e))
    return dependencies


def get_cohort_dependencies(cohort: Cohort, _warming: bool = False) -> list[int]:
    """
    Get the list of cohort IDs that the given cohort depends on.
    """
    cache_key = _cohort_dependencies_key(cohort.id)

    # Check if value exists in cache first
    cache_hit = cache.has_key(cache_key)

    def compute_dependencies():
        if not _warming:
            COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="miss").inc()
        return list(extract_cohort_dependencies(cohort))

    if cache_hit and not _warming:
        COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="hit").inc()

    result = cache.get_or_set(
        cache_key,
        compute_dependencies,
        timeout=DEPENDENCY_CACHE_TIMEOUT,
    )

    if result is None:
        logger.error("Cohort dependencies cache returned None", cohort_id=cohort.id)
    return result or []


def get_cohort_dependents(cohort: Cohort | int) -> list[int]:
    """
    Get the list of cohort IDs that depend on the given cohort.
    Can accept either a Cohort object or a cohort ID. If only an ID is provided
    and there's a cache miss, the team_id will be queried from the database.
    """
    cohort_id = cohort.id if isinstance(cohort, Cohort) else cohort
    cache_key = _cohort_dependents_key(cohort_id)

    # Check if value exists in cache first
    cache_hit = cache.has_key(cache_key)

    def compute_or_fallback() -> list[int]:
        COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="miss").inc()
        # If we only have an ID, query the database for team_id
        if isinstance(cohort, int):
            try:
                team_id = Cohort.objects.filter(pk=cohort_id, deleted=False).values_list("team_id", flat=True).first()
                if team_id is None:
                    logger.warning("Cohort not found when computing dependents", cohort_id=cohort_id)
                    return []
            except Exception as e:
                logger.exception("Failed to fetch team_id for cohort", cohort_id=cohort_id, error=str(e))
                return []
        else:
            team_id = cohort.team_id

        warm_team_cohort_dependency_cache(team_id)
        return cache.get(cache_key, [])

    if cache_hit:
        COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="hit").inc()

    result = cache.get_or_set(cache_key, compute_or_fallback, timeout=DEPENDENCY_CACHE_TIMEOUT)
    if result is None:
        logger.error("Cohort dependents cache returned None", cohort_id=cohort_id)
    return result or []


def warm_team_cohort_dependency_cache(team_id: int, batch_size: int = 1000):
    """
    Preloads the cohort dependencies and dependents cache for a given team.
    """
    dependents_map: dict[str, list[int]] = {}
    for cohort in Cohort.objects.filter(team_id=team_id, deleted=False).iterator(chunk_size=batch_size):
        # Any invalidated dependencies cache is rebuilt here
        dependents_map.setdefault(_cohort_dependents_key(cohort.id), [])
        dependencies = get_cohort_dependencies(cohort, _warming=True)
        # Dependency keys aren't fully invalidated; make sure they don't expire.
        cache.touch(_cohort_dependencies_key(cohort.id), timeout=DEPENDENCY_CACHE_TIMEOUT)
        # Build reverse map
        for dep_id in dependencies:
            dependents_map.setdefault(_cohort_dependents_key(dep_id), []).append(cohort.id)
    cache.set_many(dependents_map, timeout=DEPENDENCY_CACHE_TIMEOUT)


def _on_cohort_changed(cohort: Cohort, always_invalidate: bool = False):
    new_dependencies = extract_cohort_dependencies(cohort)
    existing_dependencies = cache.get(_cohort_dependencies_key(cohort.id))
    dependencies_changed = existing_dependencies is None or set(existing_dependencies) != new_dependencies

    # If the dependencies haven't changed, no need to refresh the cache
    if not always_invalidate and not cohort.deleted and not dependencies_changed:
        return

    cache.delete(_cohort_dependencies_key(cohort.id))
    cache.delete(_cohort_dependents_key(cohort.id))

    if existing_dependencies:
        for dep_id in existing_dependencies:
            cache.delete(_cohort_dependents_key(dep_id))

    warm_team_cohort_dependency_cache(cohort.team_id)


def _has_person_property_filters(cohort: Cohort) -> bool:
    """
    Check if a cohort has person property filters in its filters.
    Used to determine if backfill should be triggered.
    """
    return bool(_extract_person_property_filters(cohort))


def _person_property_filters_changed(cohort: Cohort) -> bool:
    """
    Check if person property filters have changed by comparing current filters
    with the previous version stored in pre_save.
    """
    try:
        # For new cohorts, always trigger if they have person property filters
        if not cohort.pk:
            return True

        # Check if we have the previous state stored from pre_save
        previous_filters = getattr(cohort, "_previous_person_property_filters", None)
        if previous_filters is None:
            # No previous state available, assume changed to be safe
            return True

        # Extract current person property filters
        current_filters = _extract_person_property_filters(cohort)

        # Compare the filters - they changed if they're not equal
        return current_filters != previous_filters

    except Exception as e:
        logger.warning(
            "error_checking_person_property_filter_changes",
            cohort_id=cohort.pk,
            error=str(e),
        )
        # If we can't determine if they changed, assume they did to be safe
        return True


def _extract_person_property_filters(cohort: Cohort) -> str:
    """
    Extract a normalized representation of person property filters from a cohort.
    Returns a hash string that can be used for comparison to detect changes.
    This captures both the individual conditions AND their logical structure.
    """
    import json
    import hashlib

    if not cohort.filters:
        return ""

    def normalize_filter_tree(node) -> dict | None:
        """Recursively traverse and normalize the filter tree structure."""
        if not isinstance(node, dict):
            return None

        node_type = node.get("type")

        # Check if this is a group node (AND/OR)
        if node_type in ("AND", "OR"):
            # Recursively process children and filter out None values
            children = []
            for child in node.get("values", []):
                normalized_child = normalize_filter_tree(child)
                if normalized_child is not None:
                    children.append(normalized_child)

            if children:
                # Sort children by their JSON representation to make order-independent
                # For AND/OR operations, the order shouldn't matter logically
                children.sort(key=lambda x: json.dumps(x, sort_keys=True))
                return {"type": node_type, "children": children}
            return None

        # This is a leaf node - check if it's a person property filter
        if node_type == "person" and node.get("conditionHash") is not None:
            # Use conditionHash to represent the condition, preserving structure
            return {"type": "person", "conditionHash": node.get("conditionHash")}

        return None

    properties = cohort.filters.get("properties")
    if not properties:
        return ""

    normalized_tree = normalize_filter_tree(properties)
    if not normalized_tree:
        return ""

    # Convert to a stable JSON representation and hash it
    normalized_json = json.dumps(normalized_tree, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized_json.encode()).hexdigest()


def _trigger_cohort_backfill(cohort: Cohort) -> None:
    """
    Trigger backfill for a realtime cohort with person properties.
    Debounces with a 5-minute delay so rapid re-saves only trigger one backfill.
    """
    try:
        from posthog.tasks.calculate_cohort import trigger_cohort_backfill_task

        redis_client = get_redis_client()
        lock_key = f"cohort_backfill_pending:{cohort.pk}"

        # Atomic set-if-not-exists with TTL. Returns True only for the first
        # caller within the window; subsequent saves are debounced.
        if redis_client.set(lock_key, 1, nx=True, ex=COHORT_BACKFILL_REDIS_TTL_SECONDS):
            logger.info(
                "triggering_cohort_backfill_on_conditions_change",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
                cohort_type=cohort.cohort_type,
                debounce_seconds=COHORT_BACKFILL_DEBOUNCE_SECONDS,
            )
            try:
                trigger_cohort_backfill_task.apply_async(
                    args=[cohort.team_id, cohort.pk],
                    countdown=COHORT_BACKFILL_DEBOUNCE_SECONDS,
                )
            except Exception:
                # Release the lock so the next save can retry scheduling
                redis_client.delete(lock_key)
                raise
        else:
            logger.info(
                "cohort_backfill_already_pending",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
            )

    except Exception as e:
        logger.exception(
            "failed_to_trigger_cohort_backfill",
            cohort_id=cohort.pk,
            team_id=cohort.team_id,
            error=str(e),
        )


@receiver(pre_save, sender=Cohort)
def cohort_pre_save(sender, instance, **kwargs):
    """
    Capture the previous state of person property filters before save.
    This is needed to compare with the new state in post_save.
    """
    try:
        # Skip non-realtime cohorts to avoid extra DB queries
        if not instance.pk or instance.cohort_type != CohortType.REALTIME:
            instance._previous_person_property_filters = ""
            return

        # Check if filters field is being updated - if not, skip the expensive DB read
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "filters" not in update_fields:
            instance._previous_person_property_filters = ""
            return

        # Get the previous version from database
        previous_cohort = Cohort.objects.get(pk=instance.pk)
        # Store the previous person property filters hash on the instance
        instance._previous_person_property_filters = _extract_person_property_filters(previous_cohort)
    except Cohort.DoesNotExist:
        # Cohort doesn't exist yet (should not happen), treat as new
        instance._previous_person_property_filters = ""
    except Exception as e:
        logger.warning(
            "error_capturing_previous_person_property_filters",
            cohort_id=instance.pk,
            error=str(e),
        )
        # If we can't capture previous state, mark as None to be safe
        instance._previous_person_property_filters = None


@receiver(post_save, sender=Cohort)
def cohort_changed(sender, instance, **kwargs):
    """
    Clear and rebuild dependency caches when cohort changes.
    """
    if is_cohort_recalculation_only_save(kwargs):
        return

    transaction.on_commit(lambda: _on_cohort_changed(instance))


@receiver(post_save, sender=Cohort)
def cohort_conditions_changed_backfill(sender, instance, **kwargs):
    """
    Trigger backfill when realtime cohort person property conditions change.
    This ensures that person property filters are properly backfilled
    when cohort filters are modified.
    """
    # Skip if this is only a recalculation update
    if is_cohort_recalculation_only_save(kwargs):
        return

    # Skip if filters field is not being updated - matches pre_save logic
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "filters" not in update_fields:
        return

    # Skip if cohort is not realtime
    if instance.cohort_type != CohortType.REALTIME:
        return

    # Skip if cohort is static
    if instance.is_static:
        return

    # Skip if cohort is deleted
    if instance.deleted:
        return

    # Check if this is a new cohort (created=True) or an update
    is_new = kwargs.get("created", False)

    if is_new:
        # For new cohorts, only trigger if they have person property filters
        if not _has_person_property_filters(instance):
            return
    else:
        # For updates, only trigger if person property filters actually changed
        if not _person_property_filters_changed(instance):
            return

    # Check feature flag before triggering backfill
    if not posthoganalytics.feature_enabled(
        "cohort-backfill-on-change",
        str(instance.team_id),
        groups={"team": str(instance.team_id)},
        send_feature_flag_events=False,
    ):
        return

    # Use transaction.on_commit to ensure backfill runs after the current transaction
    transaction.on_commit(lambda: _trigger_cohort_backfill(instance))


@receiver(post_delete, sender=Cohort)
def cohort_deleted(sender, instance, **kwargs):
    """
    Clear and rebuild dependency caches when cohort is deleted.
    """
    transaction.on_commit(lambda: _on_cohort_changed(instance, always_invalidate=True))


@receiver(post_delete, sender=Team)
def clear_team_cohort_dependency_cache(sender, instance: Team, **kwargs):
    """
    Clear cohort dependency caches for all cohorts belonging to the deleted team.
    """

    def clear_cache():
        team_cohorts = Cohort.objects.filter(team=instance, deleted=False).values_list("id", flat=True)
        for cohort_id in team_cohorts:
            cache.delete(_cohort_dependencies_key(cohort_id))
            cache.delete(_cohort_dependents_key(cohort_id))

    transaction.on_commit(clear_cache)
