from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from prometheus_client import Counter
from rest_framework.exceptions import ValidationError
from structlog import get_logger

from posthog.models.cohort.cohort import Cohort
from posthog.models.team.team import Team

logger = get_logger(__name__)
DEPENDENCY_CACHE_TIMEOUT = 7 * 24 * 60 * 60  # 1 week

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


@receiver(post_save, sender=Cohort)
def cohort_changed(sender, instance, **kwargs):
    """
    Clear and rebuild dependency caches when cohort changes.
    """

    transaction.on_commit(lambda: _on_cohort_changed(instance))


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
