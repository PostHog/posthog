from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.project import Project
    from posthog.models.team.team import Team
    from posthog.personhog_client.client import PersonHogClient

from django.contrib.postgres.fields import ArrayField
from django.db import DatabaseError, models
from django.db.models import Count
from django.utils import timezone

import structlog
from prometheus_client import Counter

from posthog.models.utils import RootTeamMixin
from posthog.person_db_router import PERSONS_DB_FOR_WRITE
from posthog.personhog_client.metrics import PERSONHOG_ROUTING_ERRORS_TOTAL, PERSONHOG_ROUTING_TOTAL, get_client_name
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

# Terminal failure of a group-type fetch, after all fallbacks. Separate from the
# personhog routing counters: these sites query the persons DB directly via the ORM
# and never call personhog, so the failure must not land on the personhog metrics.
GROUP_TYPES_FETCH_FAILURES = Counter(
    "posthog_group_types_fetch_failures",
    "Terminal failures fetching group-type mappings, by operation/source/error_type",
    labelnames=["operation", "source", "error_type"],
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
    GROUP_TYPES_FETCH_FAILURES.labels(operation=operation, source="django_orm", error_type="db_error").inc()

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


def get_group_types_for_project(project_id: int) -> list[dict[str, Any]]:
    """Fetch group types from cache, falling back to personhog then ORM, then stale cache, then empty list."""
    from posthog.personhog_client.client import get_personhog_client

    cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{project_id}"
    stale_cache_key = f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}"

    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    client = get_personhog_client()
    if client is not None:
        try:
            result = _fetch_group_types_via_personhog(client, project_id)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_group_types_for_project", source="personhog", client_name=get_client_name()
            ).inc()
            safe_cache_set(cache_key, result, GROUP_TYPES_CACHE_TTL)
            _write_project_stale_if_non_empty(project_id, result)
            return result
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_group_types_for_project",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning("personhog_group_types_failure", project_id=project_id, exc_info=True)

    try:
        result = list(
            GroupTypeMapping.objects.filter(project_id=project_id)  # nosemgrep: no-direct-persons-db-orm
            .order_by("group_type_index")
            .values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
        )
        PERSONHOG_ROUTING_TOTAL.labels(
            operation="get_group_types_for_project", source="django_orm", client_name=get_client_name()
        ).inc()
        safe_cache_set(cache_key, result, GROUP_TYPES_CACHE_TTL)
        _write_project_stale_if_non_empty(project_id, result)
        return result
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


def _fetch_group_types_for_team_via_personhog(client: PersonHogClient, team_id: int) -> list[dict[str, Any]]:
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByTeamIdRequest

    resp = client.get_group_type_mappings_by_team_id(GetGroupTypeMappingsByTeamIdRequest(team_id=team_id))
    result = [proto_group_type_mapping_to_dict(m) for m in resp.mappings]
    result.sort(key=lambda d: d["group_type_index"])
    return result


def get_group_types_for_team(team_id: int) -> list[dict[str, Any]]:
    """Fetch group types for a team via personhog, falling back to ORM on error."""
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is not None:
        try:
            result = _fetch_group_types_for_team_via_personhog(client, team_id)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_group_types_for_team", source="personhog", client_name=get_client_name()
            ).inc()
            return result
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_group_types_for_team",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning("personhog_group_types_for_team_failure", team_id=team_id, exc_info=True)

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="get_group_types_for_team", source="django_orm", client_name=get_client_name()
    ).inc()
    try:
        return list(
            GroupTypeMapping.objects.filter(team_id=team_id)  # nosemgrep: no-direct-persons-db-orm
            .order_by("group_type_index")
            .values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
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
    client: PersonHogClient, project_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdsRequest

    resp = client.get_group_type_mappings_by_project_ids(
        GetGroupTypeMappingsByProjectIdsRequest(project_ids=project_ids)
    )
    result: dict[int, list[dict[str, Any]]] = {}
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


def get_group_types_for_projects(project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Batch fetch group types for multiple projects via personhog, falling back to
    ORM, then to the per-project stale cache on a DB failure.

    Raises GroupTypesUnavailable if the persons DB is unavailable and any requested
    project has no cached last-known-good, rather than returning an all-empty
    mapping. Callers must handle that case.
    """
    from posthog.personhog_client.client import get_personhog_client

    client = get_personhog_client()
    if client is not None:
        try:
            result = _fetch_group_types_for_projects_via_personhog(client, project_ids)
            for pid in project_ids:
                result.setdefault(pid, [])
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_group_types_for_projects", source="personhog", client_name=get_client_name()
            ).inc()
            _populate_projects_stale_cache(result)
            return result
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_group_types_for_projects",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning("personhog_group_types_for_projects_failure", project_ids=project_ids, exc_info=True)

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="get_group_types_for_projects", source="django_orm", client_name=get_client_name()
    ).inc()
    result = {pid: [] for pid in project_ids}
    try:
        for row in (
            GroupTypeMapping.objects.filter(project_id__in=project_ids)  # nosemgrep: no-direct-persons-db-orm
            .order_by("group_type_index")
            .values("project_id", *GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
        ):
            pid = row.pop("project_id")
            result.setdefault(pid, []).append(row)
    except DatabaseError as exc:
        return _recover_projects_from_stale_or_fail(project_ids, exc)

    _populate_projects_stale_cache(result)
    return result


def count_group_type_mappings_per_team() -> list[dict[str, int]]:
    """Count group type mappings per team via personhog, falling back to ORM."""
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import CountGroupTypeMappingsRequest

    client = get_personhog_client()
    if client is not None:
        try:
            resp = client.count_group_type_mappings(CountGroupTypeMappingsRequest())
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="count_group_type_mappings_per_team", source="personhog", client_name=get_client_name()
            ).inc()
            return [{"team_id": c.team_id, "total": c.count} for c in resp.counts]
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="count_group_type_mappings_per_team",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning("personhog_count_group_type_mappings_failure", exc_info=True)

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="count_group_type_mappings_per_team", source="django_orm", client_name=get_client_name()
    ).inc()
    try:
        return list(
            GroupTypeMapping.objects.values("team_id")  # nosemgrep: no-direct-persons-db-orm
            .annotate(total=Count("id"))
            .order_by("team_id")  # nosemgrep: no-direct-persons-db-orm
        )
    except DatabaseError:
        logger.warning("count_group_type_mappings_orm_failure", exc_info=True)
        return []


def project_has_group_types_authoritatively(project_id: int) -> bool:
    """True if the project has group types per the persons-DB primary, or if that
    cannot be confirmed (fail closed).

    The local-eval empty-mapping guard uses this when its cheap last-known-good signal
    (the per-project stale key) is absent, so a write that would empty a populated
    mapping is only allowed when the project is *confirmed* to have no group types.

    Reads the primary (PERSONS_DB_FOR_WRITE) on purpose: the normal fetch already
    returned the suspect empty (possibly from personhog or a lagging replica), so this
    independent check must hit the source of truth rather than route through personhog
    again. On a DB error it returns True — the caller must not treat an unconfirmable
    state as safe to empty.

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
            GroupTypeMapping.objects.using(PERSONS_DB_FOR_WRITE)  # nosemgrep: no-direct-persons-db-orm
            .filter(project_id=project_id)
            .exists()
        )
    except DatabaseError:
        logger.warning("group_types_primary_confirmation_failed", project_id=project_id, exc_info=True)
        return True
    if not has_group_types:
        # Only cache the negative. A True must keep hitting the DB so a later deletion
        # is seen promptly, and the DB-error branch above must never be cached.
        safe_cache_set(confirmed_empty_key, True, GROUP_TYPES_CONFIRMED_EMPTY_CACHE_TTL)
    return has_group_types


def update_group_type_mapping_fields(
    instance: GroupTypeMapping,
    *,
    fields: dict[str, Any],
    operation: str = "group_type_update",
) -> None:
    """Update specific fields on a GroupTypeMapping via personhog, falling back to ORM.

    `fields` maps model field names to values — e.g. {"name_singular": "Org", "name_plural": "Orgs"}.
    For `detail_dashboard_id`, pass None to clear or an int to set.
    For `default_columns`, pass a list[str] or None.
    """
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import UpdateGroupTypeMappingRequest

    client = get_personhog_client()
    if client is not None:
        try:
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
            PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="personhog", client_name=get_client_name()).inc()
            return
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation=operation,
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_update_group_type_mapping_failure",
                project_id=instance.project_id,
                group_type_index=instance.group_type_index,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="django_orm", client_name=get_client_name()).inc()
    for field_name, value in fields.items():
        setattr(instance, field_name, value)
    instance.save()


def delete_group_type_mapping(instance: GroupTypeMapping) -> None:
    """Delete a GroupTypeMapping via personhog, falling back to ORM."""
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import DeleteGroupTypeMappingRequest

    client = get_personhog_client()
    if client is not None:
        try:
            client.delete_group_type_mapping(
                DeleteGroupTypeMappingRequest(
                    project_id=instance.project_id,
                    group_type_index=instance.group_type_index,
                )
            )
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="delete_group_type_mapping", source="personhog", client_name=get_client_name()
            ).inc()
            return
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="delete_group_type_mapping",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_delete_group_type_mapping_failure",
                project_id=instance.project_id,
                group_type_index=instance.group_type_index,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="delete_group_type_mapping", source="django_orm", client_name=get_client_name()
    ).inc()
    instance.delete()


def clear_dashboard_from_group_type_mapping(team_id: int, dashboard_id: int, project_id: int | None = None) -> None:
    """Clear detail_dashboard_id from any GroupTypeMapping referencing this dashboard.

    Uses GetGroupTypeMappingByDashboardId to find the mapping, then UpdateGroupTypeMapping to clear it.
    Falls back to ORM filter/update.
    """
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import GetGroupTypeMappingByDashboardIdRequest, UpdateGroupTypeMappingRequest

    client = get_personhog_client()
    if client is not None:
        try:
            resp = client.get_group_type_mapping_by_dashboard_id(
                GetGroupTypeMappingByDashboardIdRequest(team_id=team_id, dashboard_id=dashboard_id)
            )
            if resp.mapping and resp.mapping.group_type_index is not None:
                client.update_group_type_mapping(
                    UpdateGroupTypeMappingRequest(
                        project_id=resp.mapping.project_id,
                        group_type_index=resp.mapping.group_type_index,
                        update_mask=["detail_dashboard_id"],
                    )
                )
                invalidate_group_types_cache(resp.mapping.project_id)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="clear_dashboard_from_group_type_mapping", source="personhog", client_name=get_client_name()
            ).inc()
            return
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="clear_dashboard_from_group_type_mapping",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_clear_dashboard_from_group_type_mapping_failure",
                team_id=team_id,
                dashboard_id=dashboard_id,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="clear_dashboard_from_group_type_mapping", source="django_orm", client_name=get_client_name()
    ).inc()
    GroupTypeMapping.objects.using(PERSONS_DB_FOR_WRITE).filter(  # nosemgrep: no-direct-persons-db-orm
        detail_dashboard_id=dashboard_id
    ).update(  # nosemgrep: no-direct-persons-db-orm
        detail_dashboard_id=None
    )
    if project_id is not None:
        invalidate_group_types_cache(project_id)
