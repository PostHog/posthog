from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.utils import UUIDModel


class CatalogNode(UUIDModel):
    """A logical "table-shaped thing" tracked by the catalog. Exposed as system.tables."""

    class Kind(models.TextChoices):
        WAREHOUSE_TABLE = "warehouse_table", "Warehouse table"
        SAVED_QUERY = "saved_query", "Saved query"
        SYSTEM_TABLE = "system_table", "System table"
        POSTHOG_TABLE = "posthog_table", "PostHog table"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        APPROVED = "approved", "Approved"
        OFFICIAL = "official", "Official"
        DRIFT = "drift", "Drift detected"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    name = models.CharField(max_length=400)

    # Polymorphic pointer to the backing Django row (DataWarehouseTable, DataWarehouseSavedQuery,
    # or any future model). Only populated for kinds that have a backing row — system_table and
    # posthog_table nodes leave it NULL. Cleanup of stale nodes on backing-row delete is handled
    # by the signal listeners in `signals.py` rather than via DB-level cascade.
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    object_id = models.UUIDField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    last_traversed_at = models.DateTimeField(null=True, blank=True)

    synthetic_description = models.TextField(null=True, blank=True)
    semantic_role = models.CharField(max_length=64, null=True, blank=True)
    business_domain = models.CharField(max_length=64, null=True, blank=True)
    tags = ArrayField(models.CharField(max_length=64), default=list, blank=True)

    description_generated_at = models.DateTimeField(null=True, blank=True)
    generator_model = models.CharField(max_length=64, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    reviewed_by = models.ForeignKey("posthog.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "kind", "name"], name="catalog_node_unique_kind_name"),
        ]
        indexes = [
            models.Index(fields=["team", "kind"]),
            # Cascade-cleanup signals filter by (content_type, object_id); this keeps that fast.
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.name}"


class CatalogColumn(UUIDModel):
    """A column on a CatalogNode. Exposed as system.columns."""

    class SemanticType(models.TextChoices):
        ENTITY_ID = "entity_id", "Entity ID"
        FOREIGN_KEY = "foreign_key", "Foreign key"
        TIMESTAMP = "timestamp", "Timestamp"
        MEASURE = "measure", "Measure"
        DIMENSION = "dimension", "Dimension"
        MONETARY = "monetary", "Monetary"
        FREE_TEXT = "free_text", "Free text"
        ENUM = "enum", "Enum"
        UUID = "uuid", "UUID"
        UNKNOWN = "unknown", "Unknown"

    class PIIClass(models.TextChoices):
        PII = "pii", "PII"
        SENSITIVE = "sensitive", "Sensitive"
        PUBLIC = "public", "Public"
        UNKNOWN = "unknown", "Unknown"

    node = models.ForeignKey(CatalogNode, on_delete=models.CASCADE, related_name="columns")
    # Denormalized so HogQL's PostgresTable layer can apply the per-team filter directly
    # without joining through `node`. Kept in sync via upsert_column.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=400)
    position = models.IntegerField(default=0)

    clickhouse_type = models.CharField(max_length=255, null=True, blank=True)
    hogql_type = models.CharField(max_length=128, null=True, blank=True)
    nullable = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    synthetic_description = models.TextField(null=True, blank=True)
    semantic_type = models.CharField(max_length=32, choices=SemanticType.choices, null=True, blank=True)
    pii_class = models.CharField(max_length=16, choices=PIIClass.choices, null=True, blank=True)

    description_generated_at = models.DateTimeField(null=True, blank=True)
    generator_model = models.CharField(max_length=64, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["node", "name"], name="catalog_column_unique_per_node"),
        ]
        indexes = [models.Index(fields=["node"])]
        ordering = ["node_id", "position"]

    def save(self, *args, **kwargs) -> None:
        # Keep the denormalized `team_id` in sync with the parent node so callers
        # only have to set `node` — the HogQL printer expects `team_id` on every row.
        # Django's stubs type `team_id` as a non-nullable int, but at runtime it's
        # absent until first save when the caller only set `node`.
        if not getattr(self, "team_id", None) and self.node_id is not None:
            self.team_id = self.node.team_id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.node_id}.{self.name}"


class CatalogTraversalRun(UUIDModel):
    """Audit row for each cron-triggered traversal pass."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Trigger(models.TextChoices):
        CRON = "cron", "Cron"
        MANUAL = "manual", "Manual"
        API = "api", "API"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    trigger = models.CharField(max_length=16, choices=Trigger.choices)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    nodes_processed = models.IntegerField(default=0)
    columns_processed = models.IntegerField(default=0)
    relationships_proposed = models.IntegerField(default=0)
    descriptions_generated = models.IntegerField(default=0)

    generator_model = models.CharField(max_length=64, null=True, blank=True)
    config = models.JSONField(default=dict, blank=True)
    error = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["team", "-started_at"])]


class CatalogRelationship(UUIDModel):
    """An edge between two CatalogNodes. Exposed as system.relationships."""

    class Kind(models.TextChoices):
        FOREIGN_KEY = "foreign_key", "Foreign key"
        SAME_ENTITY = "same_entity", "Same entity"
        LINEAGE = "lineage", "Lineage"
        DECLARED_JOIN = "declared_join", "Declared join"
        JOIN_CANDIDATE = "join_candidate", "Join candidate"

    class Status(models.TextChoices):
        PROPOSED = "proposed", "Proposed"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        STALE = "stale", "Stale"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    source_node = models.ForeignKey(CatalogNode, on_delete=models.CASCADE, related_name="outgoing_edges")
    source_column = models.ForeignKey(CatalogColumn, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    target_node = models.ForeignKey(CatalogNode, on_delete=models.CASCADE, related_name="incoming_edges")
    target_column = models.ForeignKey(CatalogColumn, null=True, blank=True, on_delete=models.CASCADE, related_name="+")

    kind = models.CharField(max_length=32, choices=Kind.choices)
    confidence = models.FloatField()
    reasoning = models.TextField(blank=True, default="")

    discovered_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    discovered_in_run = models.ForeignKey(
        CatalogTraversalRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    generator_model = models.CharField(max_length=64, null=True, blank=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROPOSED)
    reviewed_by = models.ForeignKey("posthog.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_node", "source_column", "target_node", "target_column", "kind"],
                name="catalog_relationship_unique_edge",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["source_node"]),
            models.Index(fields=["target_node"]),
        ]
