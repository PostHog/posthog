from collections import defaultdict
from typing import Any
from uuid import uuid4

from django.conf import settings
from django.core.cache import cache, caches
from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from prometheus_client import Counter, Histogram
from rest_framework.exceptions import ValidationError
from structlog import get_logger

from posthog.models.team.team import Team
from posthog.redis import get_client as get_redis_client

from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillTrigger
from products.cohorts.backend.models.cohort import Cohort, CohortType, is_cohort_recalculation_only_save
from products.cohorts.backend.realtime_teams import is_cohort_backfill_trigger_team, is_realtime_cohort_team

logger = get_logger(__name__)
DEPENDENCY_CACHE_TIMEOUT = 7 * 24 * 60 * 60  # 1 week
# Bounds the rescans one warm does while edges keep changing under it.
DEPENDENCY_WARM_MAX_ATTEMPTS = 3

# The dependency key families are read back in the request that writes them: on create,
# `_on_cohort_changed` runs before `enqueue_calculation` reads `dependents` for the new cohort
# (on_commit callbacks run FIFO). The default cache serves reads from a replica, and a replica-lag
# miss on `dependents` rebuilds the whole team on the request path, which is the cost this module
# exists to avoid. The behavioral-ids keys stay on the default cache: only the list endpoint reads
# them.
dependency_cache = caches["cohort_dependencies"]

# A save that persists none of these fields cannot change a dependency edge.
DEPENDENCY_FIELDS = frozenset({"filters", "groups", "deleted"})
COHORT_BACKFILL_DEBOUNCE_SECONDS = 300  # 5 minutes
# The lock expiring exactly as the task fires is what closes the lost-dispatch window: a TTL longer
# than the countdown would swallow a save that lands after the task already read its state.
COHORT_BACKFILL_REDIS_TTL_SECONDS = COHORT_BACKFILL_DEBOUNCE_SECONDS

# Prometheus metrics for cache hit/miss tracking
COHORT_DEPENDENCY_CACHE_COUNTER = Counter(
    "posthog_cohort_dependency_cache_requests_total",
    "Total number of cohort dependency cache requests",
    labelnames=["cache_type", "result"],
)

COHORT_DEPENDENCY_MAINTENANCE_COUNTER = Counter(
    "posthog_cohort_dependency_maintenance_total",
    "Cohort dependency cache maintenance operations, by change kind and whether any edge was involved",
    labelnames=["operation", "path"],
)

COHORT_DEPENDENCY_WARM_COHORTS_SCANNED = Histogram(
    "posthog_cohort_dependency_warm_cohorts_scanned",
    "Cohorts scanned per team dependency cache warm",
    buckets=(1, 10, 100, 1_000, 10_000, 100_000),
)

COHORT_REALTIME_STATE_ORPHANED_COUNTER = Counter(
    "posthog_cohort_realtime_state_orphaned_total",
    "Realtime cohort edits that orphaned Stage 1 state keyed on the pre-edit definition",
    labelnames=["reason"],
)

# `not_realtime_team` is the one outcome with no log line: it fires on every save of a
# trigger-allowlisted team the realtime allowlist misses, and logging that per save would be noise
# while the misconfiguration itself deserves a signal an operator can alert on.
COHORT_BACKFILL_TRIGGER_COUNTER = Counter(
    "posthog_cohort_backfill_trigger_total",
    "Dispatch outcomes of cohort saves that were candidates for a backfill run",
    labelnames=["backfill_kind", "outcome"],
)


def _cohort_dependencies_key(cohort_id: int) -> str:
    return f"cohort:dependencies:{cohort_id}"


def _cohort_dependents_key(cohort_id: int) -> str:
    return f"cohort:dependents:{cohort_id}"


def _team_dependency_generation_key(team_id: int) -> str:
    return f"cohort:dependency_generation:{team_id}"


# Set of behavioral (flag-incompatible) cohort ids per team, hidden from the feature-flag
# property picker. Cached because the flag's cohort typeahead hits the cohorts list endpoint
# on every keystroke, and recomputing the dependency graph there means loading every cohort
# for the team into memory. The TTL is a backstop; the cache is invalidated whenever a cohort
# in the team changes (see cohort_changed / cohort_deleted). It is keyed on
# allow_realtime_backfilled because that toggles which realtime cohorts count as seeds.
BEHAVIORAL_COHORT_IDS_CACHE_TIMEOUT = 60 * 60  # 1 hour


def _behavioral_cohort_ids_key(team_id: int, allow_realtime_backfilled: bool) -> str:
    return f"cohort:flag_excluded_behavioral_ids:{team_id}:{int(allow_realtime_backfilled)}"


def _build_cohort_dependency_graph(all_cohorts: dict[int, Cohort]) -> tuple[dict[int, set[int]], set[int]]:
    """Build a directed graph of cohort dependencies and identify behavioral cohorts.

    Returns (adjacency_list, behavioral_cohort_ids). Static cohorts are skipped: they have
    pre-computed membership and don't re-evaluate their filters, so they're always safe to
    use regardless of filter type.
    """
    graph: dict[int, set[int]] = defaultdict(set)
    behavioral_cohorts: set[int] = set()

    def check_property_values(values: Any, source_id: int) -> None:
        if not isinstance(values, list):
            return

        for value in values:
            if not isinstance(value, dict):
                continue

            if value.get("type") == "behavioral":
                behavioral_cohorts.add(source_id)
            elif value.get("type") == "cohort":
                try:
                    target_id = int(value.get("value", "0"))
                except ValueError:
                    continue
                if target_id in all_cohorts:
                    graph[source_id].add(target_id)
            elif value.get("type") in ("AND", "OR") and value.get("values"):
                check_property_values(value["values"], source_id)

    for cohort_id, cohort in all_cohorts.items():
        if cohort.is_static:
            continue
        if cohort.filters:
            properties = cohort.filters.get("properties", {})
            if isinstance(properties, dict):
                check_property_values(properties.get("values", []), cohort_id)

    return graph, behavioral_cohorts


def find_behavioral_cohorts(all_cohorts: dict[int, Cohort], *, allow_realtime_backfilled: bool = False) -> set[int]:
    """Find cohorts that are behavioral, or reference (transitively) a behavioral cohort.

    A cohort is affected if it's a behavioral seed, or references one through the dependency
    graph. We walk the *reverse* graph once from the seeds (O(V+E)) — every node that can
    reach a seed via forward edges is affected.

    When allow_realtime_backfilled is True, realtime cohorts that have been backfilled are
    not seeds: they can be evaluated via the cohort_membership table during flag evaluation.
    (They can still be pulled in if they reference another seed.)
    """
    graph, behavioral_cohorts = _build_cohort_dependency_graph(all_cohorts)

    flag_compatible: set[int] = set()
    if allow_realtime_backfilled:
        flag_compatible = {
            cid for cid in behavioral_cohorts if (cohort := all_cohorts.get(cid)) and cohort.is_flag_compatible
        }
    seeds = behavioral_cohorts - flag_compatible

    # Reverse adjacency: target -> sources that reference it.
    reverse: dict[int, set[int]] = defaultdict(set)
    for source_id, targets in graph.items():
        for target_id in targets:
            reverse[target_id].add(source_id)

    affected = set(seeds)
    stack = list(seeds)
    while stack:
        node = stack.pop()
        for source_id in reverse.get(node, ()):
            if source_id not in affected:
                affected.add(source_id)
                stack.append(source_id)

    return affected


def _compute_flag_excluded_behavioral_cohort_ids(team_id: int, *, allow_realtime_backfilled: bool) -> set[int]:
    # Only non-static cohorts whose filters reference a behavioral node or another cohort can
    # be a seed or reach one; the rest are leaves that never get excluded. Filtering them out
    # in SQL keeps the in-memory graph — and the JSON we parse — small. The bare-word match
    # can't produce false negatives: a behavioral or cohort node always serializes the literal
    # "behavioral"/"cohort" substring. A false positive (e.g. a person-property value of
    # "cohort") only loads an extra leaf, which the graph walk then ignores.
    graph_source = (
        Cohort.objects.filter(team_id=team_id, deleted=False, is_static=False)
        .annotate(_filters_text=Cast("filters", output_field=TextField()))
        .filter(Q(_filters_text__icontains="behavioral") | Q(_filters_text__icontains="cohort"))
        .only(
            "id",
            "is_static",
            "filters",
            "cohort_type",
            "last_backfill_person_properties_at",
            "last_backfill_events_at",
        )
    )
    all_cohorts = {cohort.id: cohort for cohort in graph_source}
    return find_behavioral_cohorts(all_cohorts, allow_realtime_backfilled=allow_realtime_backfilled)


def get_flag_excluded_behavioral_cohort_ids(team_id: int, *, allow_realtime_backfilled: bool | None) -> set[int]:
    """Behavioral (flag-incompatible) cohort ids for a team, cached across requests."""
    # feature_enabled can return None when the flag can't be evaluated; normalize so the
    # cache key is stable and the compute path sees a real bool.
    allow_realtime_backfilled = bool(allow_realtime_backfilled)
    cache_key = _behavioral_cohort_ids_key(team_id, allow_realtime_backfilled)
    cached = cache.get(cache_key)
    if cached is not None:  # empty list is a valid cached result, not a miss
        return set(cached)

    behavioral_cohort_ids = _compute_flag_excluded_behavioral_cohort_ids(
        team_id, allow_realtime_backfilled=allow_realtime_backfilled
    )
    cache.set(cache_key, list(behavioral_cohort_ids), timeout=BEHAVIORAL_COHORT_IDS_CACHE_TIMEOUT)
    return behavioral_cohort_ids


def _invalidate_team_behavioral_cohort_cache(team_id: int) -> None:
    cache.delete_many(
        [
            _behavioral_cohort_ids_key(team_id, allow_realtime_backfilled=True),
            _behavioral_cohort_ids_key(team_id, allow_realtime_backfilled=False),
        ]
    )


# Public alias for callers outside the signal path (e.g. the backfill finalizer) that must
# explicitly invalidate the behavioral-cohort cache after bypassing signals.
invalidate_team_behavioral_cohort_cache = _invalidate_team_behavioral_cohort_cache


def extract_cohort_dependencies(cohort: Cohort, *, ignore_deleted: bool = False) -> set[int]:
    """
    Extract cohort dependencies from the given cohort.

    A deleted cohort has no dependencies unless `ignore_deleted` is set, which the delete path uses
    to find the edges it tears down.
    """
    dependencies = set()
    if ignore_deleted or not cohort.deleted:
        try:
            for prop in cohort.properties.flat:
                if prop.type == "cohort" and isinstance(prop.value, int) and prop.value != cohort.id:
                    dependencies.add(prop.value)
        except ValidationError as e:
            COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="invalid").inc()
            logger.warning("Skipping cohort with invalid filters", cohort_id=cohort.id, error=str(e))
    return dependencies


def get_cohort_dependencies(cohort: Cohort) -> list[int]:
    """
    Get the list of cohort IDs that the given cohort depends on.
    """
    cache_key = _cohort_dependencies_key(cohort.id)

    dependencies = dependency_cache.get(cache_key)
    if dependencies is not None:
        COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="hit").inc()
        return dependencies

    COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="miss").inc()
    dependencies = list(extract_cohort_dependencies(cohort))
    dependency_cache.set(cache_key, dependencies, timeout=DEPENDENCY_CACHE_TIMEOUT)
    return dependencies


def get_cohort_dependents(cohort: Cohort | int) -> list[int]:
    """
    Get the list of cohort IDs that depend on the given cohort.
    Can accept either a Cohort object or a cohort ID. If only an ID is provided
    and there's a cache miss, the team_id will be queried from the database.
    """
    cohort_id = cohort.id if isinstance(cohort, Cohort) else cohort
    cache_key = _cohort_dependents_key(cohort_id)

    dependents = dependency_cache.get(cache_key)
    if dependents is not None:
        COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="hit").inc()
        return dependents
    COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="miss").inc()

    # If we only have an ID, query the database for team_id. A soft-deleted cohort can still
    # have live dependents, so the lookup must not filter on deleted.
    if isinstance(cohort, int):
        try:
            team_id = Cohort.objects.filter(pk=cohort_id).values_list("team_id", flat=True).first()
        except Exception as e:
            logger.exception("Failed to fetch team_id for cohort", cohort_id=cohort_id, error=str(e))
            return []
    else:
        team_id = cohort.team_id

    if team_id is None:
        logger.warning("Cohort not found when computing dependents", cohort_id=cohort_id)
    else:
        warm_team_cohort_dependency_cache(team_id)

    dependents = dependency_cache.get(cache_key)
    if dependents is None:
        # The warm writes keys only for live cohorts and the cohorts they reference. Caching the
        # empty list for anything else keeps a stale id in a reverse list from rescanning the team
        # on every read.
        dependents = []
        dependency_cache.set(cache_key, dependents, timeout=DEPENDENCY_CACHE_TIMEOUT)
    return dependents


def warm_team_cohort_dependency_cache(team_id: int, batch_size: int = 1000) -> int:
    """
    Rebuilds both key families for every live cohort of a team from Postgres. Returns the number of
    cohorts scanned.

    An edge change that commits during the scan bumps the team generation before it deletes any
    reverse key. A scan that ends on a different generation than it started on may have published a
    reverse list from pre-edit rows, so it runs again and overwrites its own output. Writers never
    wait on a warm. The attempt bound caps the scans that continuous edge edits in one team can
    force on a single read miss.
    """
    generation_key = _team_dependency_generation_key(team_id)
    scanned = 0
    for _ in range(DEPENDENCY_WARM_MAX_ATTEMPTS):
        generation = dependency_cache.get(generation_key)
        scanned = _publish_team_cohort_dependencies(team_id, batch_size)
        if dependency_cache.get(generation_key) == generation:
            return scanned
    logger.warning("cohort_dependency_warm_unsettled", team_id=team_id, attempts=DEPENDENCY_WARM_MAX_ATTEMPTS)
    return scanned


def _publish_team_cohort_dependencies(team_id: int, batch_size: int) -> int:
    """
    One scan of a team's live cohorts that writes both key families. Returns the number of cohorts
    scanned.

    Uses keyset pagination on id instead of .iterator(), which opens a named
    server-side cursor that can be invalidated by connection recycling between
    batches (e.g. behind a pooler) and raises InvalidCursorName mid-scan.

    Forward keys are written per batch. The reverse map is written once at the end, because a
    dependency's dependents can span batches and a per-batch write would overwrite the earlier
    part of the list.
    """
    dependents_map: dict[str, list[int]] = {}
    scanned = 0
    last_id = 0
    while True:
        batch = list(
            Cohort.objects.filter(team_id=team_id, deleted=False, id__gt=last_id)
            .order_by("id")
            .only("id", "team_id", "deleted", "filters", "groups")[:batch_size]
        )
        if not batch:
            break
        dependencies_map: dict[str, list[int]] = {}
        for cohort in batch:
            dependencies = extract_cohort_dependencies(cohort)
            dependencies_map[_cohort_dependencies_key(cohort.id)] = list(dependencies)
            dependents_map.setdefault(_cohort_dependents_key(cohort.id), [])
            for dep_id in dependencies:
                dependents_map.setdefault(_cohort_dependents_key(dep_id), []).append(cohort.id)
        dependency_cache.set_many(dependencies_map, timeout=DEPENDENCY_CACHE_TIMEOUT)
        scanned += len(batch)
        last_id = batch[-1].id

    dependents_items = list(dependents_map.items())
    for start in range(0, len(dependents_items), batch_size):
        dependency_cache.set_many(dict(dependents_items[start : start + batch_size]), timeout=DEPENDENCY_CACHE_TIMEOUT)

    COHORT_DEPENDENCY_WARM_COHORTS_SCANNED.observe(scanned)
    return scanned


def _on_cohort_changed(
    cohort: Cohort,
    *,
    created: bool = False,
    hard_deleted: bool = False,
    update_fields: frozenset[str] | None = None,
) -> None:
    """
    Keeps the dependency key families consistent with one cohort's save or delete.

    Only the changed cohort's own keys are written. The reverse lists of the cohorts it started or
    stopped referencing are deleted rather than edited: DEL is idempotent, so two concurrent writers
    cannot lose each other's update, and the next reader rebuilds the list from Postgres. A warm that
    overlaps those deletes is fenced by the team generation, see warm_team_cohort_dependency_cache.
    """
    if not settings.COHORT_DEPENDENCY_INCREMENTAL_MAINTENANCE:
        _on_cohort_changed_full_warm(cohort, always_invalidate=hard_deleted)
        return

    if update_fields is not None and DEPENDENCY_FIELDS.isdisjoint(update_fields):
        COHORT_DEPENDENCY_MAINTENANCE_COUNTER.labels(operation="skipped", path="no_edges").inc()
        return

    removed = hard_deleted or cohort.deleted
    if created:
        operation = "create"
        # Nothing can reference an id that did not exist before this save.
        old_dependencies: set[int] = set()
    elif removed:
        operation = "hard_delete" if hard_deleted else "soft_delete"
        # The cached value may have expired, but the instance still carries the filters that
        # describe the edges being torn down.
        old_dependencies = extract_cohort_dependencies(cohort, ignore_deleted=True)
    else:
        operation = "update"
        # An expired key reads as "no previous edges", which leaves this cohort in a former
        # dependency's reverse list until the next warm. The cost is one unneeded recalculation
        # of this cohort when that former dependency recalculates, never a missed one.
        old_dependencies = set(dependency_cache.get(_cohort_dependencies_key(cohort.id)) or [])
    new_dependencies = set() if removed else extract_cohort_dependencies(cohort)

    dependencies_key = _cohort_dependencies_key(cohort.id)
    if removed:
        # A soft-deleted cohort keeps its own reverse list: live cohorts may still reference it,
        # and the scheduler follows those edges.
        own_keys = [dependencies_key]
        if hard_deleted:
            own_keys.append(_cohort_dependents_key(cohort.id))
        dependency_cache.delete_many(own_keys)
    elif created:
        dependency_cache.set_many(
            {dependencies_key: list(new_dependencies), _cohort_dependents_key(cohort.id): []},
            timeout=DEPENDENCY_CACHE_TIMEOUT,
        )
    else:
        dependency_cache.set(dependencies_key, list(new_dependencies), timeout=DEPENDENCY_CACHE_TIMEOUT)

    changed_dependencies = old_dependencies ^ new_dependencies
    if changed_dependencies:
        # The bump precedes the deletes. A warm checks the generation after it publishes, so a bump
        # that lands before that check forces a rescan. If the bump lands after the check, the
        # deletes land after the publish too and remove the stale keys themselves.
        dependency_cache.set(
            _team_dependency_generation_key(cohort.team_id), uuid4().hex, timeout=DEPENDENCY_CACHE_TIMEOUT
        )
        dependency_cache.delete_many([_cohort_dependents_key(dep_id) for dep_id in changed_dependencies])

    path = "edges" if old_dependencies or new_dependencies else "no_edges"
    COHORT_DEPENDENCY_MAINTENANCE_COUNTER.labels(operation=operation, path=path).inc()


def _on_cohort_changed_full_warm(cohort: Cohort, always_invalidate: bool = False) -> None:
    """
    Fallback behind the COHORT_DEPENDENCY_INCREMENTAL_MAINTENANCE kill switch: invalidates the
    changed cohort's keys and rescans the whole team.
    """
    new_dependencies = extract_cohort_dependencies(cohort)
    existing_dependencies = dependency_cache.get(_cohort_dependencies_key(cohort.id))
    dependencies_changed = existing_dependencies is None or set(existing_dependencies) != new_dependencies

    # If the dependencies haven't changed, no need to refresh the cache
    if not always_invalidate and not cohort.deleted and not dependencies_changed:
        return

    dependency_cache.delete(_cohort_dependencies_key(cohort.id))
    dependency_cache.delete(_cohort_dependents_key(cohort.id))

    if existing_dependencies:
        for dep_id in existing_dependencies:
            dependency_cache.delete(_cohort_dependents_key(dep_id))

    warm_team_cohort_dependency_cache(cohort.team_id)


def _has_backfillable_filters(cohort: Cohort, kind: CohortBackfillKind) -> bool:
    from products.cohorts.backend.backfill.runs import (  # noqa: PLC0415 — avoids a model-load cycle
        has_behavioral_filters,
        person_backfill_ineligibility_reason,
    )

    if kind == CohortBackfillKind.PERSON_PROPERTY:
        # The creator's own predicate, so this cannot judge backfillable a cohort the creator will
        # permanently refuse (for example one that also carries a person_metadata leaf).
        return person_backfill_ineligibility_reason(cohort) is None
    return has_behavioral_filters(cohort)


def _trigger_cohort_backfill(cohort: Cohort, trigger_kind: str, kind: CohortBackfillKind) -> None:
    """Enqueue one debounced run-creation task, at most one per cohort and kind per window.

    The Redis TTL matching the countdown is what closes the window: the key expires exactly when the
    task fires, so a save arriving after that schedules the next task instead of being swallowed.
    """
    try:
        from posthog.tasks.calculate_cohort import (
            trigger_cohort_backfill_run_task,  # noqa: PLC0415 — avoids a task import during model loading
        )

        redis_client = get_redis_client()
        lock_key = f"cohort_backfill_{kind}_pending:{cohort.pk}"
        if not redis_client.set(lock_key, 1, nx=True, ex=COHORT_BACKFILL_REDIS_TTL_SECONDS):
            COHORT_BACKFILL_TRIGGER_COUNTER.labels(backfill_kind=kind, outcome="debounced").inc()
            logger.info(
                "cohort_backfill_already_pending",
                cohort_id=cohort.pk,
                team_id=cohort.team_id,
                backfill_kind=kind,
            )
            return

        logger.info(
            "triggering_cohort_backfill",
            cohort_id=cohort.pk,
            team_id=cohort.team_id,
            backfill_kind=kind,
            trigger_kind=trigger_kind,
            debounce_seconds=COHORT_BACKFILL_DEBOUNCE_SECONDS,
        )
        try:
            trigger_cohort_backfill_run_task.apply_async(
                args=[cohort.team_id, cohort.pk, trigger_kind, kind],
                countdown=COHORT_BACKFILL_DEBOUNCE_SECONDS,
            )
        except Exception:
            # Release the lock so the next save can retry scheduling.
            redis_client.delete(lock_key)
            raise
        COHORT_BACKFILL_TRIGGER_COUNTER.labels(backfill_kind=kind, outcome="enqueued").inc()
    except Exception as error:
        COHORT_BACKFILL_TRIGGER_COUNTER.labels(backfill_kind=kind, outcome="enqueue_failed").inc()
        logger.exception(
            "failed_to_trigger_cohort_backfill",
            cohort_id=cohort.pk,
            team_id=cohort.team_id,
            backfill_kind=kind,
            error=str(error),
        )


def _backfill_trigger_kind(instance: Cohort, kwargs: dict, *, shape_changed: bool) -> str | None:
    """The trigger label for a save that should enqueue a run, or None when it should not.

    ``created`` has to be checked separately from ``shape_changed``, which compares against a stored
    hash and so is always False on an insert. Guarding on the flag alone would silently drop the
    create path.
    """
    if is_cohort_recalculation_only_save(kwargs):
        return None
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "filters" not in update_fields:
        return None
    if instance.cohort_type != CohortType.REALTIME or instance.is_static or instance.deleted:
        return None
    if kwargs.get("created", False):
        return CohortBackfillTrigger.COHORT_CREATED
    return CohortBackfillTrigger.COHORT_EDITED if shape_changed else None


def _supersede_cohort_backfills(cohort: Cohort, kind: CohortBackfillKind) -> None:
    try:
        from products.cohorts.backend.backfill.runs import (
            supersede_active_runs,  # noqa: PLC0415 — avoids a model-load cycle
        )

        supersede_active_runs(cohort.team_id, [cohort.id], kind=kind)
    except Exception as error:
        logger.exception(
            "failed_to_supersede_cohort_backfills",
            cohort_id=cohort.pk,
            team_id=cohort.team_id,
            backfill_kind=kind,
            error=str(error),
        )


@receiver(post_save, sender=Cohort)
def cohort_changed(sender, instance, **kwargs):
    """
    Clear and rebuild dependency caches when cohort changes.
    """
    if is_cohort_recalculation_only_save(kwargs):
        return

    created = kwargs.get("created", False)
    update_fields = kwargs.get("update_fields")
    transaction.on_commit(lambda: _on_cohort_changed(instance, created=created, update_fields=update_fields))
    transaction.on_commit(lambda: _invalidate_team_behavioral_cohort_cache(instance.team_id))


@receiver(post_save, sender=Cohort)
def cohort_behavioral_shape_changed_supersede(sender, instance, **kwargs):
    """Invalidate in-flight behavioral backfill runs when the cohort's behavioral leaf shape changes.

    Part of the Django-to-Rust contract, not a leftover of the removed Python backfill trigger: a run
    row pins the cohort's filters and shape hashes (see backfill/runs.py), and rust/cohort-seeder
    claims those rows to replay history. An edit mid-run leaves the seeder working from a definition
    that no longer exists, so the run has to be marked superseded. `is_realtime_cohort_team` explains
    why the allowlist bounds this: Django's edit-time invalidation must cover exactly the teams Rust
    maintains realtime membership for.

    `_leaf_shape_changed` is only set for allowlisted realtime, non-static, non-deleted cohorts on a
    real `filters` change, so it is the whole guard.
    """
    if not instance._leaf_shape_changed:
        return

    COHORT_REALTIME_STATE_ORPHANED_COUNTER.labels(reason="leaf_state_key_changed").inc()
    transaction.on_commit(lambda: _supersede_cohort_backfills(instance, CohortBackfillKind.BEHAVIORAL))


@receiver(post_save, sender=Cohort)
def cohort_person_shape_changed_supersede(sender, instance, **kwargs):
    """Invalidate in-flight person-property backfill runs when the cohort's person leaf shape changes.

    The person mirror of `cohort_behavioral_shape_changed_supersede`, and the edit-time fence the
    person readiness stamp relies on. After an A -> B -> A revert the participation's pinned person
    hash matches the cohort's current one again, so the hash CAS in `_stamp_readiness` would stamp
    readiness over a backfill whose seeded state went stale during the B window; only the
    `superseded_at` set here refuses that stamp.

    `_person_shape_changed` is only set for allowlisted realtime, non-static, non-deleted cohorts on
    a real `filters` change, so it is the whole guard.
    """
    if not instance._person_shape_changed:
        return

    COHORT_REALTIME_STATE_ORPHANED_COUNTER.labels(reason="person_condition_hash_changed").inc()
    transaction.on_commit(lambda: _supersede_cohort_backfills(instance, CohortBackfillKind.PERSON_PROPERTY))


@receiver(post_save, sender=Cohort)
def cohort_behavioral_shape_changed_backfill(sender, instance, **kwargs):
    """Enqueue a behavioral backfill run when an allowlisted team creates or edits a cohort.

    Separate from the supersede receiver above on purpose. Superseding an invalidated run is a
    correctness obligation to rust/cohort-seeder that has to hold for every realtime team, while
    creating a replacement run costs a ClickHouse history replay, so it stays behind the narrower
    `COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST`. Keeping them apart means the expensive half can be off
    for a team while the cheap half still runs.

    The trigger allowlist opts a team in on top of realtime membership, which the creators require:
    without the realtime check here, a team listed only in the trigger allowlist would debounce a
    task on every create that the creators are guaranteed to refuse, with nothing naming the cause.
    """
    try:
        if not is_cohort_backfill_trigger_team(instance.team_id):
            return
        if not is_realtime_cohort_team(instance.team_id):
            COHORT_BACKFILL_TRIGGER_COUNTER.labels(
                backfill_kind=CohortBackfillKind.BEHAVIORAL, outcome="not_realtime_team"
            ).inc()
            return
        trigger_kind = _backfill_trigger_kind(instance, kwargs, shape_changed=instance._leaf_shape_changed)
        if trigger_kind is None or not _has_backfillable_filters(instance, CohortBackfillKind.BEHAVIORAL):
            return

        transaction.on_commit(lambda: _trigger_cohort_backfill(instance, trigger_kind, CohortBackfillKind.BEHAVIORAL))
    except Exception as error:
        logger.exception(
            "failed_to_handle_cohort_behavioral_shape_change",
            cohort_id=instance.pk,
            team_id=instance.team_id,
            error=str(error),
        )


@receiver(post_save, sender=Cohort)
def cohort_person_shape_changed_backfill(sender, instance, **kwargs):
    """Enqueue a person-property backfill run when an allowlisted team creates or edits a cohort.

    The person mirror of `cohort_behavioral_shape_changed_backfill`, sharing its allowlist. A cohort
    carrying both leaf kinds gets one run of each, on separate debounce keys, because the two seed
    different stores and stamp different readiness columns.
    """
    try:
        if not is_cohort_backfill_trigger_team(instance.team_id):
            return
        if not is_realtime_cohort_team(instance.team_id):
            COHORT_BACKFILL_TRIGGER_COUNTER.labels(
                backfill_kind=CohortBackfillKind.PERSON_PROPERTY, outcome="not_realtime_team"
            ).inc()
            return
        trigger_kind = _backfill_trigger_kind(instance, kwargs, shape_changed=instance._person_shape_changed)
        if trigger_kind is None or not _has_backfillable_filters(instance, CohortBackfillKind.PERSON_PROPERTY):
            return

        transaction.on_commit(
            lambda: _trigger_cohort_backfill(instance, trigger_kind, CohortBackfillKind.PERSON_PROPERTY)
        )
    except Exception as error:
        logger.exception(
            "failed_to_handle_cohort_person_shape_change",
            cohort_id=instance.pk,
            team_id=instance.team_id,
            error=str(error),
        )


@receiver(post_delete, sender=Cohort)
def cohort_deleted(sender, instance, **kwargs):
    """
    Clear and rebuild dependency caches when cohort is deleted.
    """
    transaction.on_commit(lambda: _on_cohort_changed(instance, hard_deleted=True))
    transaction.on_commit(lambda: _invalidate_team_behavioral_cohort_cache(instance.team_id))


@receiver(post_delete, sender=Team)
def clear_team_cohort_dependency_cache(sender, instance: Team, **kwargs):
    """
    Clear cohort dependency caches for all cohorts belonging to the deleted team.
    """

    def clear_cache():
        team_cohorts = Cohort.objects.filter(team_id=instance.pk, deleted=False).values_list("id", flat=True)
        for cohort_id in team_cohorts:
            dependency_cache.delete(_cohort_dependencies_key(cohort_id))
            dependency_cache.delete(_cohort_dependents_key(cohort_id))
        _invalidate_team_behavioral_cohort_cache(instance.pk)

    transaction.on_commit(clear_cache)
