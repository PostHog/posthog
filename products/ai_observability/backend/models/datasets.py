from typing import cast

from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.expressions import NegatedExpression
from django.db.models.lookups import Exact

from posthog.models.scoping.manager import TeamScopedManager
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


def _json_type_is(field_name: str, json_type: str) -> Exact:
    return Exact(
        Func(F(field_name), function="jsonb_typeof", output_field=models.CharField()),
        Value(json_type),
    )


def _json_type_is_not(field_name: str, json_type: str) -> NegatedExpression:
    return NegatedExpression(_json_type_is(field_name, json_type))


class Dataset(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    metadata = models.JSONField(blank=True, default=dict)
    archived = models.BooleanField(default=False)
    current_revision = models.ForeignKey(
        "DatasetRevision",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "llm_analytics_dataset_v2"
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_llma_dataset_v2_team_name"),
            models.CheckConstraint(
                condition=_json_type_is("metadata", "object"),
                name="llma_dataset_v2_metadata_object",
            ),
        ]
        indexes = [
            models.Index(
                fields=["team", "archived", "-created_at", "id"],
                name="llma_dataset_v2_team_arch_idx",
            ),
            GinIndex(
                name="llma_dataset_v2_name_trgm",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                name="llma_dataset_v2_desc_trgm",
                fields=["description"],
                opclasses=["gin_trgm_ops"],
            ),
        ]


class DatasetRevision(UUIDModel, CreatedMetaFields):
    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="revisions")
    revision = models.PositiveIntegerField()

    class Meta:
        db_table = "llm_analytics_datasetrevision_v2"
        ordering = ["-revision"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "revision"],
                name="uniq_llma_dataset_revision_v2",
            ),
            models.UniqueConstraint(
                fields=["id", "dataset", "team"],
                name="uniq_llma_dataset_rev_v2_owner",
            ),
            models.CheckConstraint(
                condition=Q(revision__gte=1),
                name="llma_dataset_revision_v2_positive",
            ),
        ]


class DatasetItem(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="items")
    client_item_id = models.CharField(db_column="external_id", max_length=255, null=True, blank=True)
    current_version = models.ForeignKey(
        "DatasetItemVersion",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "llm_analytics_datasetitem_v2"
        ordering = ["-created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "client_item_id"],
                condition=Q(client_item_id__isnull=False),
                name="uniq_llma_dataset_item_v2_ext",
            ),
            models.UniqueConstraint(
                fields=["id", "dataset", "team"],
                name="uniq_llma_dataset_item_v2_owner",
            ),
        ]
        indexes = [
            models.Index(
                fields=["team", "dataset", "-created_at", "id"],
                name="llma_dataset_item_v2_list_idx",
            )
        ]


class DatasetItemVersion(UUIDModel, CreatedMetaFields):
    objects = TeamScopedManager()

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_constraint=False,
    )

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="item_versions")
    dataset_item = models.ForeignKey(DatasetItem, on_delete=models.CASCADE, related_name="versions")
    dataset_revision = models.ForeignKey(
        DatasetRevision,
        on_delete=models.RESTRICT,
        related_name="item_versions",
    )
    version = models.PositiveIntegerField()
    archived = models.BooleanField(default=False)
    input = models.JSONField()
    expected_output = models.JSONField(null=True, blank=True)
    source_output = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(blank=True, default=dict)
    source_trace_id = models.CharField(max_length=255, null=True, blank=True)
    source_event_id = models.CharField(max_length=255, null=True, blank=True)
    source_timestamp = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "llm_analytics_datasetitemversion_v2"
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_item", "version"],
                name="uniq_llma_dataset_item_version_v2",
            ),
            models.UniqueConstraint(
                fields=["dataset_item", "dataset_revision"],
                name="uniq_llma_dataset_item_revision_v2",
            ),
            models.CheckConstraint(
                condition=Q(version__gte=1),
                name="llma_dataset_item_ver_v2_positive",
            ),
            models.CheckConstraint(
                condition=_json_type_is_not("input", "null"),
                name="llma_dataset_item_ver_v2_input",
            ),
            models.CheckConstraint(
                condition=cast(
                    Q,
                    Q(expected_output__isnull=True) | _json_type_is_not("expected_output", "null"),
                ),
                name="llma_dataset_item_ver_v2_expected",
            ),
            models.CheckConstraint(
                condition=cast(
                    Q,
                    Q(source_output__isnull=True) | _json_type_is_not("source_output", "null"),
                ),
                name="llma_dataset_item_ver_v2_source",
            ),
            models.CheckConstraint(
                condition=_json_type_is("metadata", "object"),
                name="llma_dataset_item_ver_v2_metadata",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source_trace_id__isnull=True, source_event_id__isnull=True, source_timestamp__isnull=True)
                    | Q(source_trace_id__isnull=False, source_timestamp__isnull=False)
                ),
                name="llma_dataset_item_ver_v2_source_ref",
            ),
        ]
