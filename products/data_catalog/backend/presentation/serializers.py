"""DRF serializers for data_catalog.

These are the source of truth for the generated frontend/MCP types, so every field carries
help_text. ``status`` is exposed as a plain read-only string (not a ChoiceField) to keep it out of
the drf-spectacular enum namespace, where a component named ``Status`` collides across the API.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.schema_enums import IntervalType

from ..facade import api
from ..facade.api import MAX_DESCRIPTION_LENGTH, METRIC_NAME_MAX_LENGTH
from ..facade.enums import CreatedSource
from ..facade.models import Metric, RelationshipProposal, TableCertification


@extend_schema_field(OpenApiTypes.OBJECT)
class MetricDefinitionField(serializers.JSONField):
    """A machine-readable query (HogQLQuery, TrendsQuery, event node, ...). Typed as a free object."""


@extend_schema_field(OpenApiTypes.ANY)
class _FreeJSONField(serializers.JSONField):
    """A free-form JSON value (query results / query status shapes)."""


@extend_schema_serializer(component_name="DataCatalogMetricRun")
class MetricRunResponseSerializer(serializers.Serializer):
    """Normalized envelope returned by the metric-run endpoint."""

    status = serializers.CharField(help_text="Lifecycle state of the metric that produced these results.")
    is_drifted = serializers.BooleanField(
        help_text="True when the definition has drifted from its linked source insight (or the insight is gone). "
        "Only status 'approved' with is_drifted false is canonical."
    )
    unit = serializers.CharField(allow_null=True, help_text="Unit of the result, e.g. usd, percent.")
    kind = serializers.CharField(allow_null=True, help_text="Query kind that was executed.")
    results = _FreeJSONField(
        allow_null=True, help_text="The query results, for an executable metric. Null for a markdown metric."
    )
    compiled_query = serializers.CharField(allow_null=True, help_text="The compiled HogQL, when available.")
    query_status = _FreeJSONField(allow_null=True, help_text="Async query status, when the run is not blocking.")
    posthog_url = serializers.CharField(
        allow_null=True, help_text="Deep link to open the query in the app (SQL editor or insight)."
    )
    instructions = serializers.CharField(
        allow_null=True,
        help_text="For a markdown (agent-calculated) metric, the steps to follow to compute it. Null for an executable metric.",
    )


@extend_schema_serializer(component_name="DataCatalogMetricRunRequest")
class MetricRunRequestSerializer(serializers.Serializer):
    """Optional run-time overrides. The whole body may be omitted; a metric runs by its URL name."""

    date_from = serializers.CharField(
        required=False,
        help_text="Override the start of the query window (e.g. '-7d'). Rejected for HogQLQuery metrics, whose window is fixed in SQL.",
    )
    date_to = serializers.CharField(required=False, help_text="Override the end of the query window.")
    interval = serializers.ChoiceField(
        choices=[t.value for t in IntervalType],
        required=False,
        help_text="Override the bucket interval. Rejected for HogQLQuery metrics.",
    )
    query_id = serializers.CharField(required=False, help_text="Client-supplied id to correlate or cancel the run.")


@extend_schema_serializer(component_name="DataCatalogMetricRunQuery")
class MetricRunQuerySerializer(serializers.Serializer):
    """Query params for the metric-run endpoint."""

    refresh = serializers.ChoiceField(
        choices=["blocking", "async", "lazy_async", "force_blocking", "force_async", "force_cache"],
        required=False,
        help_text="Cache/execution behavior, same semantics as /query/. Omit to serve a fresh cache "
        "hit and calculate blocking when stale.",
    )


@extend_schema_serializer(component_name="DataCatalogMetric")
class MetricSerializer(serializers.ModelSerializer):
    definition = MetricDefinitionField(
        required=False,
        allow_null=True,
        help_text="Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.",
    )
    definition_kind = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.",
    )
    status = serializers.CharField(
        read_only=True,
        help_text="Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately.",
    )
    is_drifted = serializers.SerializerMethodField(
        help_text="True when the definition has drifted from its linked source insight (or the insight is gone).",
    )
    created_source = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in CreatedSource],
        required=False,
        help_text="Whether a human ('user') or an agent ('ai_generated') authored this metric.",
    )
    owner = serializers.SerializerMethodField(
        help_text="Email of the human accountable for this metric, or null.",
    )
    created_by = UserBasicSerializer(read_only=True, help_text="User who first created this metric.")
    approved_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who approved this metric as canonical, or null."
    )

    class Meta:
        model = Metric
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "unit",
            "owner",
            "definition",
            "definition_kind",
            "referenced_table_names",
            "status",
            "is_drifted",
            "approved_at",
            "approved_by",
            "source_insight_short_id",
            "last_run_at",
            "created_source",
            "ai_model",
            "confidence",
            "reasoning",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "approved_at",
            "approved_by",
            "referenced_table_names",
            "last_run_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {
                "help_text": "Identifier-safe run handle, unique among the team's live metrics. Renaming or "
                "deleting a metric frees its name for reuse, and anything referencing the old name (SQL over "
                "information_schema.metrics, run URLs, links) stops resolving."
            },
            "source_insight_short_id": {
                "required": False,
                "help_text": "Create the metric from this insight's query (snapshotted server-side). "
                "Set to null to unlink. Mutually exclusive with definition.",
            },
            "display_name": {"help_text": "Human-friendly label. Mutable, unlike name."},
            "description": {
                "help_text": "What the metric means and what it serves, in 1-3 short sentences: the business "
                "meaning plus any load-bearing inclusions/exclusions or grain. Never narrate or restate the "
                "query - the definition carries the mechanics; put rationale for query choices in 'reasoning'.",
                "max_length": MAX_DESCRIPTION_LENGTH,
            },
            "unit": {"help_text": "Unit of the result, e.g. usd, percent, cents."},
            "ai_model": {"help_text": "Model that generated the metric, if AI-authored."},
            "confidence": {
                "help_text": "AI author's confidence in the proposal, 0-1.",
                "min_value": 0.0,
                "max_value": 1.0,
            },
            "reasoning": {"help_text": "AI author's reasoning, surfaced as review context."},
        }

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_owner(self, obj: Metric) -> str | None:
        return obj.owner.email if obj.owner else None

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_is_drifted(self, obj: Metric) -> bool:
        # The list view precomputes drift for the whole page into ``drift_map`` (one bulk query);
        # single-object paths (retrieve, create, approve, ...) fall back to a bounded per-object query.
        drift_map = self.context.get("drift_map")
        if drift_map is not None and obj.id in drift_map:
            return drift_map[obj.id]
        return api.compute_drift([obj])[obj.id]


@extend_schema_serializer(component_name="DataCatalogMetricBulkNamesRequest")
class MetricBulkNamesRequestSerializer(serializers.Serializer):
    """Input for the bulk metric actions: the metric names to act on."""

    names = serializers.ListField(
        child=serializers.CharField(max_length=METRIC_NAME_MAX_LENGTH),
        allow_empty=False,
        # `allow_empty` alone doesn't reach the OpenAPI schema; `min_length` emits `minItems: 1`
        # so generated MCP/Zod clients can't construct an empty batch the API would 400.
        min_length=1,
        max_length=api.METRIC_BULK_MAX,
        help_text=f"Names of the metrics to act on, at most {api.METRIC_BULK_MAX}. Duplicates are collapsed.",
    )


@extend_schema_serializer(component_name="DataCatalogMetricBulkSkip")
class MetricBulkSkipSerializer(serializers.Serializer):
    """A metric the bulk action did not act on, and why."""

    name = serializers.CharField(help_text="Name of the metric that was skipped.")
    reason = serializers.CharField(
        help_text="Why it was skipped, e.g. 'Not found', 'Already approved', 'Drifted from its source insight'."
    )


@extend_schema_serializer(component_name="DataCatalogMetricBulkApprove")
class MetricBulkApproveResponseSerializer(serializers.Serializer):
    """Outcome of a bulk approve: what changed, and what was left alone."""

    approved = MetricSerializer(many=True, help_text="The metrics that are now approved, freshly serialized.")
    skipped = MetricBulkSkipSerializer(many=True, help_text="Requested metrics that were not approved, with reasons.")


@extend_schema_serializer(component_name="DataCatalogMetricBulkDelete")
class MetricBulkDeleteResponseSerializer(serializers.Serializer):
    """Outcome of a bulk delete: which names are gone, and what was left alone."""

    deleted = serializers.ListField(
        child=serializers.CharField(), help_text="Names of the metrics that were deleted, now free for reuse."
    )
    skipped = MetricBulkSkipSerializer(many=True, help_text="Requested metrics that were not deleted, with reasons.")


@extend_schema_serializer(component_name="DataCatalogCertification")
class CertificationSerializer(serializers.ModelSerializer):
    status = serializers.CharField(
        read_only=True, help_text="proposed, certified (prefer this source), or deprecated (avoid this source)."
    )
    proposed_status = serializers.CharField(
        read_only=True,
        help_text="The mark the proposal asks for: 'certified' (trust this source) or 'deprecated' "
        "(avoid this source). Informational once the mark is settled.",
    )
    target_type = serializers.SerializerMethodField(help_text="Whether the marked target is a 'table' or a 'view'.")
    target_name = serializers.SerializerMethodField(help_text="Queryable HogQL name of the marked table or view.")
    certified_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who last set certified/deprecated, or null."
    )

    class Meta:
        model = TableCertification
        fields = [
            "id",
            "table",
            "saved_query",
            "target_type",
            "target_name",
            "status",
            "proposed_status",
            "notes",
            "certified_by",
            "certified_at",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "table",
            "saved_query",
            "status",
            "proposed_status",
            "certified_by",
            "certified_at",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {"notes": {"help_text": "Why this mark exists, e.g. 'canonical MRR source'."}}

    @extend_schema_field(OpenApiTypes.STR)
    def get_target_type(self, obj: TableCertification) -> str:
        return "table" if obj.table_id else "view"

    @extend_schema_field(OpenApiTypes.STR)
    def get_target_name(self, obj: TableCertification) -> str:
        return api.certification_target_name(obj)


class CertificationCreateSerializer(serializers.Serializer):
    """Input for proposing a certification: address the target by id or (convenience) by name."""

    table_id = serializers.UUIDField(required=False, help_text="Warehouse table id to certify (XOR the other targets).")
    saved_query_id = serializers.UUIDField(required=False, help_text="Warehouse view (saved query) id to certify.")
    table_name = serializers.CharField(
        required=False, help_text="Queryable HogQL table name; 409 with candidates if ambiguous."
    )
    view_name = serializers.CharField(
        required=False, help_text="Queryable HogQL view name; 409 with candidates if ambiguous."
    )
    notes = serializers.CharField(required=False, allow_blank=True, help_text="Why this mark exists.")
    proposed_status = serializers.ChoiceField(
        choices=["certified", "deprecated"],
        required=False,
        default="certified",
        help_text="Intent of the proposal: 'certified' to propose trusting this source, "
        "'deprecated' to propose avoiding it (e.g. a stale or wrong source).",
    )


@extend_schema_serializer(component_name="DataCatalogRelationshipProposal")
class RelationshipProposalSerializer(serializers.ModelSerializer):
    status = serializers.CharField(
        read_only=True, help_text="proposed, accepted (promoted to a real join), or rejected (never re-proposed)."
    )
    configuration = _FreeJSONField(required=False, help_text="Extra join configuration, e.g. a field mapping.")
    evidence = _FreeJSONField(required=False, help_text="Sampling evidence: match rates, sample values.")
    reviewed_by = UserBasicSerializer(
        read_only=True, allow_null=True, help_text="User who accepted or rejected the proposal."
    )

    class Meta:
        model = RelationshipProposal
        fields = [
            "id",
            "source_table_name",
            "source_table_key",
            "joining_table_name",
            "joining_table_key",
            "field_name",
            "configuration",
            "confidence",
            "reasoning",
            "evidence",
            "status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "created_join",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "reviewed_by",
            "reviewed_at",
            "rejection_reason",
            "created_join",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {
            "source_table_name": {"help_text": "Name of the table the join starts from."},
            "source_table_key": {"help_text": "HogQL key expression on the source table (casts allowed)."},
            "joining_table_name": {"help_text": "Name of the table being joined in."},
            "joining_table_key": {"help_text": "HogQL key expression on the joining table (casts allowed)."},
            "field_name": {"help_text": "Accessor the join adds to the source table."},
            "confidence": {"help_text": "Discovery confidence in this join, 0-1."},
            "reasoning": {"help_text": "Why this join is proposed."},
        }


class RelationshipRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Why the proposal is rejected. Persisted so it is never re-proposed.",
    )
