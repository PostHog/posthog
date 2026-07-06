from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.project import Project
    from posthog.models.team.team import Team
    from posthog.personhog_client.client import PersonHogClient

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import DatabaseError, models
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.models.utils import RootTeamMixin
from posthog.personhog_client import ReadConsistency, consistency_to_read_options
from posthog.personhog_client.client import personhog_call, require_personhog_client
from posthog.rbac.decorators import field_access_control
from posthog.storage.hypercache import HyperCacheDependencyUnavailable
from posthog.utils import capture_exception_throttled, get_safe_cache, safe_cache_delete, safe_cache_set

logger = structlog.get_logger(__name__)

GROUP_TYPES_CACHE_TTL = 60 * 5  # 5 minutes
GROUP_TYPES_STALE_CACHE_TTL = 60 * 60 * 24  # 24 hours — last-known-good fallback during outages
GROUP_TYPES_NEGATIVE_CACHE_TTL = 30  # seconds — short so we detect DB recovery quickly
GROUP_TYPES_CONFIRMED_EMPTY_CACHE_TTL = 60 * 5  # 5 minutes — bounds the corruption window if invalidation is missed
GROUP_TYPES_CACHE_KEY_PREFIX = "group_types_for_project_"
GROUP_TYPES_STALE_CACHE_KEY_PREFIX = "group_types_for_project_stale_"
GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX = "group_types_for_project_confirmed_empty_"

# Throttle window for capturing group-type fetch failures, shared across processes
# via the cache so many workers failing at once report at most once per window.
GROUP_TYPES_FAILURE_CAPTURE_THROTTLE_TTL = 60  # seconds

# Terminal failure of a group-type fetch, after all fallbacks (stale cache, etc.).
GROUP_TYPES_FETCH_FAILURES = Counter(
    "posthog_group_types_fetch_failures",
    "Terminal failures fetching group-type mappings, by operation/source/error_type",
    labelnames=["operation", "source", "error_type"],
)

# A project the eventual (replica) batch read returned empty for despite a populated
# last-known-good. The `outcome` records what the strong (primary) re-read found:
# "primary_had_rows" (replica silently dropped it, corrected), "confirmed_empty"
# (genuinely empty now), or "primary_unavailable_used_stale" (primary read failed,
# served last-known-good rather than an unconfirmed empty).
GROUP_TYPES_REPLICA_EMPTY_DISCREPANCIES = Counter(
    "posthog_group_types_replica_empty_discrepancies",
    "Projects the eventual batch read returned empty for despite a populated last-known-good",
    labelnames=["operation", "outcome"],
)


class GroupTypesUnavailable(HyperCacheDependencyUnavailable):
    """Raised by the batch fetch when group types cannot be loaded and no
    last-known-good is cached for one or more projects.

    Callers fail closed instead of persisting an empty mapping: an empty mapping
    makes every group-aggregated flag for the team evaluate to false. Subclasses the
    storage-layer base so HyperCache can catch it without importing this type.
    """

    def __init__(self, project_ids: list[int]) -> None:
        super().__init__(f"Group types unavailable for projects: {project_ids}")
        self.project_ids = project_ids


def _record_group_types_fetch_failure(*, operation: str, log_event: str, exc: BaseException, **log_fields: Any) -> None:
    """Record a terminal group-type fetch failure: increment the failure counter, log
    the traceback, and capture the exception (throttled across processes).

    The counter is always incremented; only the capture is throttled. Each log line
    records whether the capture ran or was throttled.
    """
    GROUP_TYPES_FETCH_FAILURES.labels(operation=operation, source="personhog", error_type="db_error").inc()

    throttle_key = f"group_types_failure_capture_throttle:{operation}"
    captured = capture_exception_throttled(throttle_key, exc, GROUP_TYPES_FAILURE_CAPTURE_THROTTLE_TTL)

    logger.exception(
        log_event,
        operation=operation,
        error_type="db_error",
        exception_captured=captured,
        capture_throttled=not captured,
        **log_fields,
    )


# Defined here for reuse between OS and EE
GROUP_TYPE_MAPPING_SERIALIZER_FIELDS = [
    "group_type",
    "group_type_index",
    "name_singular",
    "name_plural",
    "detail_dashboard",
    "default_columns",
    "created_at",
]


# This table is responsible for mapping between group types for a Team/Project and event columns
# to add group keys
class GroupTypeMapping(RootTeamMixin, models.Model):
    # DO_NOTHING: Team/Project deletion handled manually via GroupTypeMapping.objects.filter(team_id=...).delete()
    # in delete_bulky_postgres_data(). Django CASCADE doesn't work across separate databases.
    # db_constraint=False: No database FK constraint - GroupTypeMapping may live in separate database from Team/Project
    team = models.ForeignKey("Team", on_delete=models.DO_NOTHING, db_constraint=False)
    project = models.ForeignKey("Project", on_delete=models.DO_NOTHING, db_constraint=False)
    group_type = models.CharField(max_length=400, null=False, blank=False)
    group_type_index = models.IntegerField(null=False, blank=False)
    # Used to display in UI
    name_singular = field_access_control(models.CharField(max_length=400, null=True, blank=True), "project", "admin")
    name_plural = field_access_control(models.CharField(max_length=400, null=True, blank=True), "project", "admin")

    default_columns = field_access_control(ArrayField(models.TextField(), null=True, blank=True), "project", "admin")

    # DO_NOTHING + db_constraint=False: Dashboard deletion handled manually, may be cross-database
    detail_dashboard = field_access_control(
        models.ForeignKey(
            "dashboards.Dashboard", on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True
        ),
        "project",
        "admin",
    )
    created_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        indexes = [
            models.Index(
                fields=("project", "group_type"),
                name="posthog_group_type_proj_idx",
            ),
            models.Index(
                fields=("project", "group_type_index"),
                name="posthog_group_type_i_proj_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(fields=("project", "group_type"), name="unique group types for project"),
            models.UniqueConstraint(
                fields=("project", "group_type_index"), name="unique event column indexes for project"
            ),
            models.CheckConstraint(
                condition=models.Q(group_type_index__lte=5),
                name="group_type_index is less than or equal 5",
            ),
            models.CheckConstraint(
                name="group_type_project_id_is_not_null",
                # We have this as a constraint rather than IS NOT NULL on the field, because setting IS NOT NULL cannot
                # be done without locking the table. By adding this constraint using Postgres's `NOT VALID` option
                # (via Django `AddConstraintNotValid()`) and subsequent `VALIDATE CONSTRAINT`, we avoid locking.
                condition=models.Q(project_id__isnull=False),
            ),
        ]

    def save(self, *args, **kwargs):
        # Replicate Django's auto_now_add logic: set created_at only on creation
        if self._state.adding and self.created_at is None:
            self.created_at = timezone.now()
        super().save(*args, **kwargs)


def invalidate_group_types_cache(project_id: int) -> None:
    safe_cache_delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{project_id}")
    safe_cache_delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}")
    # Clear the confirmed-empty marker so a team adding its first group type stops
    # short-circuiting project_has_group_types_authoritatively to False immediately.
    safe_cache_delete(f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}{project_id}")


def _fetch_group_types_via_personhog(client: PersonHogClient, project_id: int) -> list[dict[str, Any]]:
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest

    resp = client.get_group_type_mappings_by_project_id(GetGroupTypeMappingsByProjectIdRequest(project_id=project_id))
    result = [proto_group_type_mapping_to_dict(m) for m in resp.mappings]
    result.sort(key=lambda d: d["group_type_index"])
    return result


def get_group_types_for_project(project_id: int, *, caller_tag: str | None = None) -> list[dict[str, Any]]:
    """Fetch group types from cache, falling back to personhog, then stale cache, then empty list."""
    cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{project_id}"
    stale_cache_key = f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}"

    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    try:
        client = require_personhog_client()
        result = personhog_call(
            "get_group_types_for_project",
            lambda: _fetch_group_types_via_personhog(client, project_id),
            caller_tag=f"group_type_mapping/{caller_tag or 'get_group_types_for_project'}",
            reraise_as=DatabaseError,
        )
    except DatabaseError as exc:
        _record_group_types_fetch_failure(
            operation="get_group_types_for_project",
            log_event="persons_db_group_types_failure",
            exc=exc,
            project_id=project_id,
        )
        stale = get_safe_cache(stale_cache_key)
        if stale is not None:
            safe_cache_set(cache_key, stale, GROUP_TYPES_NEGATIVE_CACHE_TTL)
            return stale
        safe_cache_set(cache_key, [], GROUP_TYPES_NEGATIVE_CACHE_TTL)
        return []

    safe_cache_set(cache_key, result, GROUP_TYPES_CACHE_TTL)
    _write_project_stale_if_non_empty(project_id, result)
    return result


def _fetch_group_types_for_team_via_personhog(client: PersonHogClient, team_id: int) -> list[dict[str, Any]]:
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByTeamIdRequest

    resp = client.get_group_type_mappings_by_team_id(GetGroupTypeMappingsByTeamIdRequest(team_id=team_id))
    result = [proto_group_type_mapping_to_dict(m) for m in resp.mappings]
    result.sort(key=lambda d: d["group_type_index"])
    return result


def get_group_types_for_team(team_id: int, *, caller_tag: str | None = None) -> list[dict[str, Any]]:
    """Fetch group types for a team via personhog."""
    try:
        client = require_personhog_client()
        return personhog_call(
            "get_group_types_for_team",
            lambda: _fetch_group_types_for_team_via_personhog(client, team_id),
            caller_tag=f"group_type_mapping/{caller_tag or 'get_group_types_for_team'}",
            reraise_as=DatabaseError,
        )
    except DatabaseError as exc:
        _record_group_types_fetch_failure(
            operation="get_group_types_for_team",
            log_event="persons_db_group_types_for_team_failure",
            exc=exc,
            team_id=team_id,
        )
        return []


def _fetch_group_types_for_projects_via_personhog(
    client: PersonHogClient, project_ids: list[int], *, consistency: ReadConsistency = "eventual"
) -> dict[int, list[dict[str, Any]]]:
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdsRequest

    read_options = consistency_to_read_options(consistency)
    result: dict[int, list[dict[str, Any]]] = {}
    for i in range(0, len(project_ids), settings.PERSONHOG_BATCH_SIZE):
        resp = client.get_group_type_mappings_by_project_ids(
            GetGroupTypeMappingsByProjectIdsRequest(
                project_ids=project_ids[i : i + settings.PERSONHOG_BATCH_SIZE],
                read_options=read_options,
            )
        )
        for batch in resp.results:
            mappings = [proto_group_type_mapping_to_dict(m) for m in batch.mappings]
            mappings.sort(key=lambda d: d["group_type_index"])
            result[batch.key] = mappings
    return result


_REQUEST_CACHED_GROUP_TYPES_ATTR = "_request_cached_group_types"


def cached_group_types_for_team(team: Team) -> list[dict[str, Any]]:
    """Memoise `get_group_types_for_project` per request on the team instance.

    Sibling SerializerMethodFields (`has_group_types` + `group_types`) both want
    the same answer; without this memo each render hits the Redis cache twice.
    The cache lives on the model instance, which is request-scoped in practice —
    DRF builds a fresh serializer + ORM instance per request and callers do not
    retain instances across requests.
    """
    return _memoise_group_types_on(team, team.project_id)


def cached_group_types_for_project(project: Project) -> list[dict[str, Any]]:
    """Memoise `get_group_types_for_project` per request on the project instance.

    See `cached_group_types_for_team` — same memo, same lifetime, sibling
    serializer's project-shaped equivalent.
    """
    return _memoise_group_types_on(project, project.id)


def _memoise_group_types_on(target: Team | Project, project_id: int) -> list[dict[str, Any]]:
    if not hasattr(target, _REQUEST_CACHED_GROUP_TYPES_ATTR):
        setattr(target, _REQUEST_CACHED_GROUP_TYPES_ATTR, get_group_types_for_project(project_id))
    return getattr(target, _REQUEST_CACHED_GROUP_TYPES_ATTR)


def _write_project_stale_if_non_empty(project_id: int, mappings: list[dict[str, Any]]) -> None:
    """Persist a project's group types to its stale (last-known-good) key, only when
    non-empty. Overwriting a populated entry with [] would erase the fallback the
    outage recovery and the write-side empty-mapping guard depend on.
    """
    if mappings:
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}", mappings, GROUP_TYPES_STALE_CACHE_TTL)


def _populate_projects_stale_cache(result: dict[int, list[dict[str, Any]]]) -> None:
    """Write each project's non-empty group types to its per-project stale key, the
    last-known-good shared by the batch and single-project paths.

    Empty results are skipped: overwriting a populated entry with an empty list would
    erase the fallback that outage recovery and the write-side guard read.
    """
    for project_id, mappings in result.items():
        _write_project_stale_if_non_empty(project_id, mappings)


def _recover_projects_from_stale_or_fail(project_ids: list[int], exc: DatabaseError) -> dict[int, list[dict[str, Any]]]:
    """Recover a batch fetch from the per-project stale cache after a DB failure.

    Records the failure, then serves each project's last-known-good. Raises
    GroupTypesUnavailable if any project has no stale entry, so the caller never
    persists an all-empty mapping over populated data.
    """
    _record_group_types_fetch_failure(
        operation="get_group_types_for_projects",
        log_event="persons_db_group_types_for_projects_failure",
        exc=exc,
        project_ids=project_ids,
    )

    recovered: dict[int, list[dict[str, Any]]] = {}
    unrecovered: list[int] = []
    for project_id in project_ids:
        stale = get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}")
        if stale is not None:
            recovered[project_id] = stale
        else:
            unrecovered.append(project_id)

    if unrecovered:
        raise GroupTypesUnavailable(unrecovered)

    return recovered


def _reconfirm_emptied_projects_against_primary(
    result: dict[int, list[dict[str, Any]]], project_ids: list[int], *, caller_tag: str | None = None
) -> dict[int, list[dict[str, Any]]]:
    """Guard against a lagging or inconsistent replica silently dropping a project's
    group types.

    The batch fetch reads at eventual consistency (the replica pool), which can return
    an empty mapping for a project that authoritatively has group types. That silent
    empty is what makes the downstream flag-cache write try to erase a populated
    mapping. When a project reads empty but has a populated last-known-good (stale key),
    re-read just those projects from the primary at strong consistency and trust that
    answer — the primary is authoritative for both "was dropped" and "genuinely empty
    now" (e.g. the last group type was deleted).

    Projects that read empty with no last-known-good are treated as genuinely having no
    group types (the common case). They are not re-confirmed, so this adds no primary
    load on the hot path unless a real drop is detected. The write-side guard remains the
    backstop for that cold-cache edge.
    """
    suspect_ids = [
        pid
        for pid in project_ids
        if not result.get(pid) and get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{pid}") is not None
    ]
    if not suspect_ids:
        return result

    try:
        client = require_personhog_client()
        confirmed = personhog_call(
            "get_group_types_for_projects_reconfirm",
            lambda: _fetch_group_types_for_projects_via_personhog(client, suspect_ids, consistency="strong"),
            caller_tag=f"group_type_mapping/{caller_tag or 'get_group_types_for_projects'}/reconfirm",
            reraise_as=DatabaseError,
        )
    except DatabaseError:
        # Primary confirmation failed. Serve each project's last-known-good rather than
        # the replica's unconfirmed empty, so we never hand back a silent [] over data
        # we know was populated.
        for pid in suspect_ids:
            stale = get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{pid}")
            if stale:
                result[pid] = stale
                GROUP_TYPES_REPLICA_EMPTY_DISCREPANCIES.labels(
                    operation="get_group_types_for_projects", outcome="primary_unavailable_used_stale"
                ).inc()
        return result

    for pid in suspect_ids:
        primary_rows = confirmed.get(pid) or []
        if primary_rows:
            result[pid] = primary_rows
            GROUP_TYPES_REPLICA_EMPTY_DISCREPANCIES.labels(
                operation="get_group_types_for_projects", outcome="primary_had_rows"
            ).inc()
            logger.warning(
                "group_types_replica_returned_empty_primary_had_rows",
                project_id=pid,
                row_count=len(primary_rows),
            )
        else:
            GROUP_TYPES_REPLICA_EMPTY_DISCREPANCIES.labels(
                operation="get_group_types_for_projects", outcome="confirmed_empty"
            ).inc()
    return result


def get_group_types_for_projects(
    project_ids: list[int], *, caller_tag: str | None = None
) -> dict[int, list[dict[str, Any]]]:
    """Batch fetch group types for multiple projects via personhog, falling back to
    the per-project stale cache on failure.

    The batch read is at eventual consistency; any project that reads empty despite a
    populated last-known-good is re-confirmed against the primary so a lagging replica
    cannot silently return an empty mapping for a project that has group types.

    Raises GroupTypesUnavailable if personhog is unavailable and any requested
    project has no cached last-known-good, rather than returning an all-empty
    mapping. Callers must handle that case.
    """

    def _fn() -> dict[int, list[dict[str, Any]]]:
        client = require_personhog_client()
        result = _fetch_group_types_for_projects_via_personhog(client, project_ids)
        for pid in project_ids:
            result.setdefault(pid, [])
        return result

    try:
        result = personhog_call(
            "get_group_types_for_projects",
            _fn,
            caller_tag=f"group_type_mapping/{caller_tag or 'get_group_types_for_projects'}",
            reraise_as=DatabaseError,
        )
    except DatabaseError as exc:
        return _recover_projects_from_stale_or_fail(project_ids, exc)

    result = _reconfirm_emptied_projects_against_primary(result, project_ids, caller_tag=caller_tag)
    _populate_projects_stale_cache(result)
    return result


def count_group_type_mappings_per_team(*, caller_tag: str | None = None) -> list[dict[str, int]]:
    """Count group type mappings per team via personhog."""
    from posthog.personhog_client.proto import CountGroupTypeMappingsRequest

    try:
        client = require_personhog_client()
        return personhog_call(
            "count_group_type_mappings_per_team",
            lambda: [
                {"team_id": c.team_id, "total": c.count}
                for c in client.count_group_type_mappings(CountGroupTypeMappingsRequest()).counts
            ],
            caller_tag=f"group_type_mapping/{caller_tag or 'count_group_type_mappings_per_team'}",
            reraise_as=DatabaseError,
        )
    except DatabaseError:
        logger.warning("count_group_type_mappings_orm_failure", exc_info=True)
        return []


def project_has_group_types_authoritatively(project_id: int) -> bool:
    """True if the project has group types per a strong-consistency read, or if that
    cannot be confirmed (fail closed).

    The local-eval empty-mapping guard uses this when its cheap last-known-good signal
    (the per-project stale key) is absent, so a write that would empty a populated
    mapping is only allowed when the project is *confirmed* to have no group types.

    Uses _fetch_group_types_for_project_direct with "strong" consistency so the read
    hits the primary, not a lagging replica.  On any error it returns True — the caller
    must not treat an unconfirmable state as safe to empty.

    A short-lived "confirmed empty" marker caches the authoritative False so a team
    that has never had group types — the common case, where this fires on every
    no-group rebuild — doesn't probe the writer DB each time. invalidate_group_types_cache
    clears the marker when a group type is created, and the short TTL bounds the window
    if that invalidation is ever missed.
    """
    confirmed_empty_key = f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}{project_id}"
    if get_safe_cache(confirmed_empty_key):
        return False

    try:
        has_group_types = (
            len(_fetch_group_types_for_project_direct(project_id, "strong", caller_tag="flags/has-group-types")) > 0
        )
    except DatabaseError:
        logger.warning("group_types_primary_confirmation_failed", project_id=project_id, exc_info=True)
        return True

    if not has_group_types:
        safe_cache_set(confirmed_empty_key, True, GROUP_TYPES_CONFIRMED_EMPTY_CACHE_TTL)
    return has_group_types


def _dict_to_group_type_mapping_model(
    row: dict[str, Any],
    *,
    project_id: int,
    team: Team | None = None,
) -> GroupTypeMapping:
    """Build an unsaved GroupTypeMapping from a get_group_types_for_project dict.

    The instance is NOT database-backed — it carries data in memory so serializers
    and attribute access work without a round-trip.  Mark _state.adding = False so
    Django treats it as "existing" for serializer context, but note that save() will
    not work — writes go through update_group_type_mapping_fields instead.
    """
    detail_dashboard_id = row.get("detail_dashboard", row.get("detail_dashboard_id"))
    obj = GroupTypeMapping(
        project_id=project_id,
        team=team,
        group_type=row["group_type"],
        group_type_index=row["group_type_index"],
        name_singular=row.get("name_singular"),
        name_plural=row.get("name_plural"),
        detail_dashboard_id=detail_dashboard_id,
        default_columns=row.get("default_columns"),
        created_at=row.get("created_at"),
    )
    obj._state.adding = False
    return obj


def _fetch_group_types_for_project_direct(
    project_id: int,
    consistency: ReadConsistency,
    *,
    caller_tag: str | None = None,
) -> list[dict[str, Any]]:
    """Cache-bypassing read at the requested consistency level."""
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest

    client = require_personhog_client()
    return personhog_call(
        "get_group_types_for_project_direct",
        lambda: sorted(
            [
                proto_group_type_mapping_to_dict(m)
                for m in client.get_group_type_mappings_by_project_id(
                    GetGroupTypeMappingsByProjectIdRequest(
                        project_id=project_id,
                        read_options=consistency_to_read_options(consistency),
                    )
                ).mappings
            ],
            key=lambda d: d["group_type_index"],
        ),
        caller_tag=f"group_type_mapping/{caller_tag or 'get_group_types_for_project_direct'}",
        reraise_as=DatabaseError,
    )


def get_group_type_mapping_instance(
    project_id: int,
    group_type_index: int,
    *,
    team: Team | None = None,
    consistency: ReadConsistency | None = None,
    caller_tag: str | None = None,
) -> GroupTypeMapping:
    """Fetch a single GroupTypeMapping by (project_id, group_type_index) via personhog.

    When consistency is None (default), uses the cached get_group_types_for_project
    helper.  If the mapping isn't in the cached results, invalidates the cache and
    retries once before raising GroupTypeMapping.DoesNotExist.

    When consistency is set (e.g. "strong"), skips the cache and does a direct read
    at the requested consistency level — use "strong" before writes to avoid acting
    on stale data.
    """
    if consistency is not None:
        rows = _fetch_group_types_for_project_direct(project_id, consistency, caller_tag=caller_tag)
        for row in rows:
            if row["group_type_index"] == group_type_index:
                return _dict_to_group_type_mapping_model(row, project_id=project_id, team=team)
        raise GroupTypeMapping.DoesNotExist(
            f"GroupTypeMapping matching query does not exist: project_id={project_id}, group_type_index={group_type_index}"
        )

    rows = get_group_types_for_project(project_id, caller_tag=caller_tag)
    for row in rows:
        if row["group_type_index"] == group_type_index:
            return _dict_to_group_type_mapping_model(row, project_id=project_id, team=team)

    # Cache may be stale — bust it and retry once via personhog.
    invalidate_group_types_cache(project_id)
    rows = get_group_types_for_project(project_id, caller_tag=caller_tag)
    for row in rows:
        if row["group_type_index"] == group_type_index:
            return _dict_to_group_type_mapping_model(row, project_id=project_id, team=team)

    raise GroupTypeMapping.DoesNotExist(
        f"GroupTypeMapping matching query does not exist: project_id={project_id}, group_type_index={group_type_index}"
    )


def update_group_type_mapping_fields(
    instance: GroupTypeMapping,
    *,
    fields: dict[str, Any],
    caller_tag: str | None = None,
) -> None:
    """Update specific fields on a GroupTypeMapping via personhog.

    `fields` maps model field names to values — e.g. {"name_singular": "Org", "name_plural": "Orgs"}.
    For `detail_dashboard_id`, pass None to clear or an int to set.
    For `default_columns`, pass a list[str] or None.
    """
    from posthog.personhog_client.proto import UpdateGroupTypeMappingRequest

    client = require_personhog_client()

    def _fn() -> None:
        update_mask: list[str] = list(fields.keys())
        kwargs: dict[str, Any] = {
            "project_id": instance.project_id,
            "group_type_index": instance.group_type_index,
            "update_mask": update_mask,
        }
        if "name_singular" in fields:
            kwargs["name_singular"] = fields["name_singular"] or ""
        if "name_plural" in fields:
            kwargs["name_plural"] = fields["name_plural"] or ""
        if "detail_dashboard_id" in fields:
            if fields["detail_dashboard_id"] is not None:
                kwargs["detail_dashboard_id"] = fields["detail_dashboard_id"]
        if "default_columns" in fields:
            if fields["default_columns"] is not None:
                kwargs["default_columns"] = json.dumps(fields["default_columns"]).encode()
        client.update_group_type_mapping(UpdateGroupTypeMappingRequest(**kwargs))

    personhog_call(
        "update_group_type_mapping_fields",
        _fn,
        caller_tag=f"group_type_mapping/{caller_tag or 'update_group_type_mapping_fields'}",
        reraise_as=DatabaseError,
    )
    for field_name, value in fields.items():
        setattr(instance, field_name, value)


def delete_group_type_mapping(instance: GroupTypeMapping, *, caller_tag: str | None = None) -> None:
    """Delete a GroupTypeMapping via personhog."""
    from posthog.personhog_client.proto import DeleteGroupTypeMappingRequest

    client = require_personhog_client()
    personhog_call(
        "delete_group_type_mapping",
        lambda: client.delete_group_type_mapping(
            DeleteGroupTypeMappingRequest(
                project_id=instance.project_id,
                group_type_index=instance.group_type_index,
            )
        ),
        caller_tag=f"group_type_mapping/{caller_tag or 'delete_group_type_mapping'}",
        reraise_as=DatabaseError,
    )


def clear_dashboard_from_group_type_mapping(
    team_id: int, dashboard_id: int, project_id: int | None = None, *, caller_tag: str | None = None
) -> None:
    """Clear detail_dashboard_id from any GroupTypeMapping referencing this dashboard.

    Uses GetGroupTypeMappingByDashboardId to find the mapping, then UpdateGroupTypeMapping to clear it.
    """
    from posthog.personhog_client.proto import GetGroupTypeMappingByDashboardIdRequest, UpdateGroupTypeMappingRequest

    client = require_personhog_client()

    def _fn() -> None:
        resp = client.get_group_type_mapping_by_dashboard_id(
            GetGroupTypeMappingByDashboardIdRequest(team_id=team_id, dashboard_id=dashboard_id)
        )
        if resp.HasField("mapping"):
            client.update_group_type_mapping(
                UpdateGroupTypeMappingRequest(
                    project_id=resp.mapping.project_id,
                    group_type_index=resp.mapping.group_type_index,
                    update_mask=["detail_dashboard_id"],
                )
            )
            invalidate_group_types_cache(resp.mapping.project_id)

    personhog_call(
        "clear_dashboard_from_group_type_mapping",
        _fn,
        caller_tag=f"group_type_mapping/{caller_tag or 'clear_dashboard_from_group_type_mapping'}",
        reraise_as=DatabaseError,
    )
