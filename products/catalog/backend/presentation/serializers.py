"""
DRF serializers for catalog.

Outputs wrap the frozen DTOs from `facade.contracts` via DataclassSerializer.
Inputs use plain serializers because the param dataclasses require team_id
(which comes from the URL, not the body) and DataclassSerializer would fail
to instantiate the params with team_id excluded. The viewset builds the
params dataclass explicitly.

Every input field has `help_text` — these descriptions flow through OpenAPI
into the generated MCP tool schemas. Agents read them to understand what to
pass.
"""

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import CatalogColumnDTO, CatalogGraphDTO, CatalogNodeDTO, CatalogRelationshipDTO

# --- Output serializers -------------------------------------------------------


class CatalogColumnDTOSerializer(DataclassSerializer):
    class Meta:
        dataclass = CatalogColumnDTO


class CatalogNodeDTOSerializer(DataclassSerializer):
    # Not read_only: @validated_request round-trips responses through is_valid()
    # in DEBUG, and a read-only field would be stripped from validated_data,
    # breaking the nested CatalogNodeDTO reconstruction.
    columns = CatalogColumnDTOSerializer(many=True)

    class Meta:
        dataclass = CatalogNodeDTO


class CatalogRelationshipDTOSerializer(DataclassSerializer):
    class Meta:
        dataclass = CatalogRelationshipDTO


class CatalogGraphDTOSerializer(DataclassSerializer):
    """Bundles nodes and relationships for the graph view. Drives the React Flow scene
    so the client can render the whole topology in one fetch."""

    nodes = CatalogNodeDTOSerializer(many=True, read_only=True)
    relationships = CatalogRelationshipDTOSerializer(many=True, read_only=True)

    class Meta:
        dataclass = CatalogGraphDTO


# --- Input serializers --------------------------------------------------------


class UpsertNodeInputSerializer(serializers.Serializer):
    """Body for catalog-nodes-create. team_id is taken from the URL, not the body."""

    kind = serializers.ChoiceField(
        choices=["warehouse_table", "saved_query", "system_table", "posthog_table"],
        help_text=(
            "What kind of catalog entry this is. `warehouse_table` for an imported data warehouse table, "
            "`saved_query` for a derived view, `system_table` for a built-in PostHog system table like "
            "`events` or `persons`, `posthog_table` for other first-party tables."
        ),
    )
    name = serializers.CharField(
        max_length=400,
        help_text=(
            "Stable identifier for the node, unique per (team, kind). For warehouse tables this is the "
            "imported table name (e.g. `stripe_charges`). For system tables use the canonical name "
            "(e.g. `events`). The agent looks nodes up by name before upserting, so keep this stable across runs."
        ),
    )
    warehouse_table_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Set when `kind=warehouse_table` to bind this node to the backing `DataWarehouseTable` row. "
            "Used for cascade cleanup when the warehouse table is deleted. Leave null for system/posthog tables."
        ),
    )
    saved_query_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Set when `kind=saved_query` to bind this node to the backing `DataWarehouseSavedQuery` row. "
            "Leave null for non-saved-query kinds."
        ),
    )
    synthetic_description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Markdown description of what this table contains, when to use it, caveats, and how it relates "
            "to other tables. Written by the agent or human. Becomes the primary signal future agent runs use "
            "to pick the right table for a question."
        ),
    )
    semantic_role = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text=(
            "Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`, "
            "`event_source`, `identity`. Helps the agent reason about join cardinality and aggregation safety."
        ),
    )
    business_domain = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text=(
            "Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`. Used to group "
            "related tables in discovery and to scope cross-source queries."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        help_text=(
            "Free-form tags for filtering and grouping. Lowercase, short. Examples: `pii`, `derived`, "
            "`incremental`, `stripe`, `canonical`."
        ),
    )
    generator_model = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text=(
            "Identifier of the model that produced this row when generated by an agent — e.g. `claude-opus-4-7`. "
            "Leave null when humans author the description. Used for auditing autofill quality over time."
        ),
    )
    confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text=(
            "Agent's confidence (0..1) in the description and semantic tagging it just wrote. "
            "Surfaces as a draft/confirmed indicator and lets review workflows prioritize low-confidence rows."
        ),
    )


class UpsertColumnInputSerializer(serializers.Serializer):
    """Body for catalog-columns-create. Identified by (node_id, name)."""

    node_id = serializers.UUIDField(help_text="ID of the parent CatalogNode (returned by catalog-nodes-create).")
    name = serializers.CharField(
        max_length=400,
        help_text=(
            "Column name as it appears in the underlying table. Case-sensitive. Combined with `node_id` "
            "to form the upsert key — calling create again with the same (node_id, name) updates in place."
        ),
    )
    position = serializers.IntegerField(
        required=False,
        default=0,
        help_text="Ordinal position of the column in the source table. Used for display and stable iteration.",
    )
    clickhouse_type = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=255,
        help_text=(
            "Raw ClickHouse type string (`String`, `Nullable(DateTime64(3))`, `Array(String)`...). "
            "Set when the column comes from a ClickHouse-backed table; null for Postgres-only sources."
        ),
    )
    hogql_type = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=128,
        help_text=(
            "HogQL-normalized type — `String`, `Int`, `Float`, `Boolean`, `DateTime`, `Array`, `JSON`. "
            "What the agent sees when reading via `system.columns`. Inferred from clickhouse_type when not set explicitly."
        ),
    )
    nullable = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether the column can hold NULL values. Drives null-handling guidance in generated queries.",
    )
    synthetic_description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "What the column represents in business terms — meaning, units, valid values, gotchas. "
            'Example: "Subscription monthly recurring revenue in USD cents. Excludes refunds. Null for one-time charges."'
        ),
    )
    semantic_type = serializers.ChoiceField(
        choices=[
            "entity_id",
            "foreign_key",
            "timestamp",
            "measure",
            "dimension",
            "monetary",
            "free_text",
            "enum",
            "uuid",
            "unknown",
        ],
        required=False,
        allow_null=True,
        help_text=(
            "Role of the column for query planning. `entity_id` for primary identifiers, `foreign_key` for "
            "join targets, `timestamp` for time filtering, `measure` for aggregation, `dimension` for group-by, "
            "`monetary` for currency, `free_text` for unstructured prose, `enum` for closed value sets."
        ),
    )
    pii_class = serializers.ChoiceField(
        choices=["pii", "sensitive", "public", "unknown"],
        required=False,
        allow_null=True,
        help_text=(
            "Sensitivity classification. `pii` for personally identifiable (email, name, IP), `sensitive` for "
            "business-confidential, `public` for safe-to-export, `unknown` to defer classification."
        ),
    )
    generator_model = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text="Model that generated the description/typing — same convention as on nodes.",
    )
    confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Agent confidence (0..1) in the description and semantic typing.",
    )


class UpdateNodeInputSerializer(serializers.Serializer):
    """Body for catalog-nodes-partial-update. Every field optional; only supplied fields are written."""

    name = serializers.CharField(
        required=False,
        max_length=400,
        help_text="Rename the node. Must remain unique per (team, kind). Avoid renaming once agents have linked to it.",
    )
    synthetic_description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Markdown description of what this table contains, when to use it, caveats, and how it relates "
            "to other tables. Becomes the primary signal future agent runs use to pick the right table."
        ),
    )
    semantic_role = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text="Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`.",
    )
    business_domain = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text="Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        help_text="Free-form lowercase tags. Replaces the existing tag list when supplied.",
    )
    confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Agent confidence (0..1). Humans can override or clear to mark the row as verified.",
    )
    status = serializers.ChoiceField(
        choices=["proposed", "approved", "official", "drift"],
        required=False,
        help_text=(
            "Review state. `proposed` for AI-authored / unreviewed, `approved` once a human has confirmed it, "
            "`official` for canonical definitions, `drift` when the agent detects schema or semantic drift."
        ),
    )


class UpdateColumnInputSerializer(serializers.Serializer):
    """Body for catalog-columns-partial-update. Every field optional."""

    synthetic_description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="What the column represents in business terms — meaning, units, valid values, gotchas.",
    )
    semantic_type = serializers.ChoiceField(
        choices=[
            "entity_id",
            "foreign_key",
            "timestamp",
            "measure",
            "dimension",
            "monetary",
            "free_text",
            "enum",
            "uuid",
            "unknown",
        ],
        required=False,
        allow_null=True,
        help_text="Role of the column for query planning. See create endpoint for full semantics.",
    )
    pii_class = serializers.ChoiceField(
        choices=["pii", "sensitive", "public", "unknown"],
        required=False,
        allow_null=True,
        help_text="Sensitivity classification. `pii`, `sensitive`, `public`, or `unknown`.",
    )
    confidence = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=0.0,
        max_value=1.0,
        help_text="Agent confidence (0..1) in the description and semantic typing.",
    )


class UpdateRelationshipInputSerializer(serializers.Serializer):
    """Body for catalog-relationships-partial-update. Used by reviewers to accept/reject proposals."""

    status = serializers.ChoiceField(
        choices=["proposed", "accepted", "rejected", "stale"],
        required=False,
        help_text=(
            "Review state. `proposed` is the initial state, `accepted` once a human confirms the edge, "
            "`rejected` to dismiss it, `stale` when the underlying schema has moved on."
        ),
    )
    confidence = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="Reviewer's confidence (0..1) in the edge after manual inspection.",
    )
    reasoning = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-text justification, typically extended during human review.",
    )


class ProposeRelationshipInputSerializer(serializers.Serializer):
    """Body for catalog-relationships-create. Always lands in PROPOSED status until reviewed."""

    source_node_id = serializers.UUIDField(
        help_text="ID of the node the relationship originates from — e.g. the fact table, source side of a join."
    )
    target_node_id = serializers.UUIDField(
        help_text=(
            "ID of the node the relationship points to. For joins this is the other table; for foreign keys, "
            "the referenced table."
        )
    )
    kind = serializers.ChoiceField(
        choices=["foreign_key", "same_entity", "lineage", "declared_join", "join_candidate", "depends_on"],
        help_text=(
            "Relationship type. `foreign_key` when the source column references a target PK. `same_entity` "
            "when two columns identify the same business object (Stripe.customer_id ≈ Postgres.users.id). "
            "`lineage` when the target table is derived from the source (data-flow lineage). "
            "`declared_join` for an officially supported join. `join_candidate` for an inferred-but-unconfirmed "
            "join. `depends_on` for a logical dependency that isn't data-flow lineage (e.g. a metric "
            "built from an event definition or property)."
        ),
    )
    confidence = serializers.FloatField(
        min_value=0.0,
        max_value=1.0,
        help_text=(
            "Agent's confidence (0..1) that this relationship is correct. Drives the review queue — low-confidence "
            "edges surface for human approval before agents trust them for joins."
        ),
    )
    source_column_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Narrows the source side to a specific column. Set for foreign-key and join edges; null for table-level lineage.",
    )
    target_column_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Narrows the target side to a specific column. Same semantics as source_column_id.",
    )
    reasoning = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text=(
            "Free-text justification for the proposal — the data points or column-name signals the agent used. "
            "Surfaces in the review UI so a human can decide whether to accept or reject."
        ),
    )
    discovered_in_run_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="ID of the CatalogTraversalRun this relationship was discovered in. Leave null for ad-hoc proposals.",
    )
    generator_model = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text="Model that proposed the relationship — same convention as on nodes and columns.",
    )
