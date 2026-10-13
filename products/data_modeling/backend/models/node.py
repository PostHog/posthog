from collections.abc import Sequence
from typing import Any, TypedDict

from django.db import models
from django.db.models import Q
from django.utils import timezone

from posthog.models import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

from .dag import DAG


class NodeType(models.TextChoices):
    TABLE = "table"
    VIEW = "view"
    MAT_VIEW = "matview"
    ENDPOINT = "endpoint"
    METRIC = "metric"


SAVED_QUERY_NODE_TYPES = frozenset({NodeType.VIEW, NodeType.MAT_VIEW, NodeType.ENDPOINT})
_SAVED_QUERY_NODE_TYPE_VALUES = sorted(node_type.value for node_type in SAVED_QUERY_NODE_TYPES)


# properties["system"] marker set by consolidate_dags --adopt-unresolvable when a query's SQL
# would not resolve and its node was created without edges. A successful sync clears it.
DEGRADED_SYNC_KEY = "degraded_sync"

UNRESOLVED_DEPENDENCIES_KEY = "unresolved"

MAX_SYNC_ERROR_LENGTH = 500


class DegradedSyncMarker(TypedDict):
    error: str
    at: str


class UnresolvedDependenciesMarker(TypedDict):
    names: list[str]
    at: str


class LineageIssueKind(models.TextChoices):
    SYNC_FAILED = "sync_failed"
    UNRESOLVED = "unresolved"


class Node(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="+")
    team_id: int

    # models.PROTECT prevents deleting a saved query if its referenced by a Node
    saved_query = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.PROTECT, null=True, blank=True)
    saved_query_id: int | None

    metric_id = models.UUIDField(null=True, blank=True)

    dag = models.ForeignKey(DAG, on_delete=models.CASCADE, db_column="dag_fk_id")
    dag_id: int

    # name of the source table, view, matview, etc.
    # for nodes with a saved_query, this is automatically synced from saved_query.name
    name = models.TextField(max_length=2048, db_index=True)
    # type of the node (source table, view, or mat view)
    type = models.TextField(max_length=16, choices=NodeType, default=NodeType.TABLE)
    description = models.TextField(max_length=1024, default="", blank=True)
    source_control_path = models.TextField(
        blank=True, default="", help_text="File path in the source control repository for synced nodes"
    )
    properties = models.JSONField(default=dict)

    def mark_lineage_sync_failed(self, error: str) -> None:
        marker: DegradedSyncMarker = {
            "error": str(error)[:MAX_SYNC_ERROR_LENGTH],
            "at": timezone.now().isoformat(),
        }
        self.properties.setdefault("system", {})[DEGRADED_SYNC_KEY] = marker

    def mark_lineage_unresolved(self, names: Sequence[str]) -> None:
        marker: UnresolvedDependenciesMarker = {"names": list(names), "at": timezone.now().isoformat()}
        self.properties.setdefault("system", {})[UNRESOLVED_DEPENDENCIES_KEY] = marker

    def clear_lineage_markers(self) -> None:
        system = (self.properties or {}).get("system")
        if not isinstance(system, dict):
            return
        system.pop(DEGRADED_SYNC_KEY, None)
        system.pop(UNRESOLVED_DEPENDENCIES_KEY, None)
        if not system:
            self.properties.pop("system", None)

    @property
    def lineage_issue(self) -> dict[str, Any] | None:
        system = (self.properties or {}).get("system") or {}
        degraded = system.get(DEGRADED_SYNC_KEY)
        if isinstance(degraded, dict):
            return {
                "kind": LineageIssueKind.SYNC_FAILED.value,
                "detail": degraded.get("error") or "",
                "at": degraded.get("at"),
            }
        unresolved = system.get(UNRESOLVED_DEPENDENCIES_KEY)
        if not isinstance(unresolved, dict) or not unresolved.get("names"):
            return None
        return {
            "kind": LineageIssueKind.UNRESOLVED.value,
            "detail": ", ".join(unresolved["names"]),
            "at": unresolved.get("at"),
        }

    def save(self, *args, **kwargs):
        # always inherit name from saved_query when one exists
        if self.saved_query is not None:
            self.name = self.saved_query.name
        elif not self.name:
            raise ValueError("Node without a saved_query must have a name")
        super().save(*args, **kwargs)

    class Meta:
        db_table = "posthog_datamodelingnode"
        constraints = [
            models.CheckConstraint(
                name="node_backing_reference_matches_type",
                condition=(
                    Q(type=NodeType.TABLE, metric_id__isnull=True)
                    | Q(
                        type__in=_SAVED_QUERY_NODE_TYPE_VALUES,
                        saved_query__isnull=False,
                        metric_id__isnull=True,
                    )
                    | Q(type=NodeType.METRIC, saved_query__isnull=True, metric_id__isnull=False)
                ),
            ),
            models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=False),
                name="saved_query_unique_within_team_dag",
                fields=["team", "dag", "saved_query"],
            ),
            models.UniqueConstraint(
                condition=models.Q(metric_id__isnull=False),
                name="metric_unique_within_team_dag",
                fields=["team", "dag", "metric_id"],
            ),
            models.UniqueConstraint(
                condition=models.Q(saved_query__isnull=True, metric_id__isnull=True),
                name="name_unique_within_team_dag_for_tables_v2",
                fields=["team", "dag", "name"],
            ),
        ]
