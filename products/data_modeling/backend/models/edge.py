from django.db import connection, models, transaction

from posthog.models import Team
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from .node import Node

DISALLOWED_UPDATE_FIELDS = ("dag_id", "source", "source_id", "target", "target_id", "team", "team_id")


class CycleDetectionError(Exception):
    """The exception raised when an edge would cause a cycle in a DAG"""

    pass


class DAGMismatchError(Exception):
    """exception raised when an edge would connect two different DAGs together"""

    pass


class DataModelingEdgeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        for key in DISALLOWED_UPDATE_FIELDS:
            if key in kwargs:
                raise NotImplementedError(
                    f"QuerySet.update() is disabled for fields ({DISALLOWED_UPDATE_FIELDS}) to ensure cycle detection. "
                    "Use individual save() calls instead."
                )
        return super().update(**kwargs)

    def bulk_create(self, objs, *args, **kwargs):
        del objs, args, kwargs  # unused
        raise NotImplementedError("bulk_create() is disabled for Edge objects to ensure cycle detection.")

    def bulk_update(self, objs, fields, *args, **kwargs):
        for key in DISALLOWED_UPDATE_FIELDS:
            if key in kwargs:
                raise NotImplementedError(
                    f"QuerySet.bulk_update() is disabled for fields ({DISALLOWED_UPDATE_FIELDS}) to ensure cycle detection. "
                    "Use individual save() calls instead."
                )
        return super().bulk_update(objs, fields, *args, **kwargs)


class DataModelingEdgeManager(models.Manager):
    def get_queryset(self):
        return DataModelingEdgeQuerySet(self.model, using=self._db)


class Edge(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    objects = DataModelingEdgeManager()

    team = models.ForeignKey(Team, on_delete=models.CASCADE, editable=False)
    # the source node of the edge (i.e. the node this edge is pointed away from)
    source = models.ForeignKey(Node, related_name="outgoing_edges", on_delete=models.CASCADE, editable=False)
    # the target node of the edge (i.e. the node this edge is pointed toward)
    target = models.ForeignKey(Node, related_name="incoming_edges", on_delete=models.CASCADE, editable=False)
    # the name of the DAG this edge belongs to
    dag_id = models.TextField(max_length=256, default="posthog", db_index=True, editable=False)
    properties = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_datamodelingedge"
        constraints = [
            models.UniqueConstraint(fields=["dag_id", "source", "target"], name="unique_within_dag"),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self._detect_cycles()
            self._detect_dag_mismatch()
            super().save(*args, **kwargs)

    def _detect_cycles(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [self.team_id, self.dag_id])
        # trivial case: self loop
        if self.source_id == self.target_id:
            raise CycleDetectionError(
                f"Self-loop detected: team={self.team_id} dag={self.dag_id} "
                f"source={self.source_id} target={self.target_id}"
            )
        # recursive case
        if self._creates_cycle():
            raise CycleDetectionError(
                f"Cycle detected: team={self.team_id} dag={self.dag_id} source={self.source_id} target={self.target_id}"
            )

    def _creates_cycle(self):
        sql = """
            WITH RECURSIVE reachable(node_id) AS (
                SELECT e.target_id
                FROM posthog_datamodelingedge e
                WHERE e.source_id = '{target_id}'
                    AND e.team_id = '{team_id}'
                    AND e.dag_id = '{dag_id}'
                UNION
                SELECT e.target_id
                FROM posthog_datamodelingedge e
                INNER JOIN reachable r
                ON e.source_id = r.node_id
                WHERE e.target_id <> '{target_id}'
                    AND e.team_id = '{team_id}'
                    AND e.dag_id = '{dag_id}'
            )
            SELECT 1 FROM reachable WHERE node_id = '{source_id}'
        """
        with connection.cursor() as cursor:
            cursor.execute(
                sql.format(team_id=self.team_id, dag_id=self.dag_id, source_id=self.source_id, target_id=self.target_id)
            )
            return cursor.fetchone() is not None

    def _detect_dag_mismatch(self):
        source = Node.objects.get(id=self.source_id)
        target = Node.objects.get(id=self.target_id)
        if source.team_id != self.team_id or target.team_id != self.team_id:
            raise DAGMismatchError(
                f"Edge team_id ({self.team_id}) does not match "
                f"source node team_id ({source.team_id}) or "
                f"target node team_id ({target.team_id})"
            )
        if source.dag_id != self.dag_id or target.dag_id != self.dag_id:
            raise DAGMismatchError(
                f"Edge dag_id ({self.dag_id}) does not match "
                f"source node dag_id ({source.dag_id}) or "
                f"target node dag_id ({target.dag_id})"
            )
