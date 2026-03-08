from typing import Any

from django.contrib.postgres.fields import ArrayField
from django.db import DatabaseError, models
from django.utils import timezone

import structlog

from posthog.models.utils import RootTeamMixin
from posthog.personhog_client.metrics import PERSONHOG_ROUTING_ERRORS_TOTAL, PERSONHOG_ROUTING_TOTAL
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
        models.ForeignKey("Dashboard", on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True),
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
                check=models.Q(group_type_index__lte=5),
                name="group_type_index is less than or equal 5",
            ),
            models.CheckConstraint(
                name="group_type_project_id_is_not_null",
                # We have this as a constraint rather than IS NOT NULL on the field, because setting IS NOT NULL cannot
                # be done without locking the table. By adding this constraint using Postgres's `NOT VALID` option
                # (via Django `AddConstraintNotValid()`) and subsequent `VALIDATE CONSTRAINT`, we avoid locking.
                check=models.Q(project_id__isnull=False),
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


def _fetch_group_types_via_personhog(project_id: int) -> list[dict[str, Any]]:
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_group_type_mapping_to_dict
    from posthog.personhog_client.proto import GetGroupTypeMappingsByProjectIdRequest

    client = get_personhog_client()
    if client is None:
        raise RuntimeError("personhog client not configured")

    resp = client.get_group_type_mappings_by_project_id(GetGroupTypeMappingsByProjectIdRequest(project_id=project_id))
    result = [proto_group_type_mapping_to_dict(m) for m in resp.mappings]
    result.sort(key=lambda d: d["group_type_index"])
    return result


def get_group_types_for_project(project_id: int) -> list[dict[str, Any]]:
    """Fetch group types from cache, falling back to personhog/ORM, then stale cache, then empty list."""
    from posthog.personhog_client.gate import use_personhog

    cache_key = f"{GROUP_TYPES_CACHE_KEY_PREFIX}{project_id}"
    stale_cache_key = f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}"

    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    if use_personhog():
        try:
            result = _fetch_group_types_via_personhog(project_id)
            PERSONHOG_ROUTING_TOTAL.labels(operation="get_group_types_for_project", source="personhog").inc()
            safe_cache_set(cache_key, result, GROUP_TYPES_CACHE_TTL)
            safe_cache_set(stale_cache_key, result, GROUP_TYPES_STALE_CACHE_TTL)
            return result
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_group_types_for_project", source="personhog", error_type="grpc_error"
            ).inc()
            logger.warning("personhog_group_types_failure", project_id=project_id, exc_info=True)

    try:
        result = list(
            GroupTypeMapping.objects.filter(project_id=project_id)
            .order_by("group_type_index")
            .values(*GROUP_TYPE_MAPPING_SERIALIZER_FIELDS)
        )
        PERSONHOG_ROUTING_TOTAL.labels(operation="get_group_types_for_project", source="django_orm").inc()
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
