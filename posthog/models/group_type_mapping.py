from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from posthog.models.project import Project
    from posthog.models.team.team import Team
    from posthog.personhog_client.client import PersonHogClient

from django.contrib.postgres.fields import ArrayField
from django.db import DatabaseError, models
from django.utils import timezone

import structlog

from posthog.models.utils import RootTeamMixin
from posthog.personhog_client.metrics import PERSONHOG_ROUTING_ERRORS_TOTAL, PERSONHOG_ROUTING_TOTAL, get_client_name
from posthog.rbac.decorators import field_access_control
from posthog.utils import get_safe_cache, safe_cache_delete, safe_cache_set

logger = structlog.get_logger(__name__)

GROUP_TYPES_CACHE_TTL = 60 * 5  # 5 minutes
GROUP_TYPES_STALE_CACHE_TTL = 60 * 60 * 24  # 24 hours — last-known-good fallback during outages
GROUP_TYPES_NEGATIVE_CACHE_TTL = 30  # seconds — short so we detect DB recovery quickly
GROUP_TYPES_CACHE_KEY_PREFIX = "group_types_for_project_"
GROUP_TYPES_STALE_CACHE_KEY_PREFIX = "group_types_for_project_stale_"

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
            safe_cache_set(stale_cache_key, result, GROUP_TYPES_STALE_CACHE_TTL)
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
        safe_cache_set(stale_cache_key, result, GROUP_TYPES_STALE_CACHE_TTL)
        return result
    except DatabaseError:
        logger.warning("persons_db_group_types_failure", project_id=project_id, exc_info=True)
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
    except DatabaseError:
        logger.warning("persons_db_group_types_for_team_failure", team_id=team_id, exc_info=True)
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


def get_group_types_for_projects(project_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """Batch fetch group types for multiple projects via personhog, falling back to ORM on error."""
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
    except DatabaseError:
        logger.warning("persons_db_group_types_for_projects_failure", project_ids=project_ids, exc_info=True)
    return result


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

    from posthog.person_db_router import PERSONS_DB_FOR_WRITE

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
