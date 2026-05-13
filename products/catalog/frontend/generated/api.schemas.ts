/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `entity_id` - entity_id
 * `foreign_key` - foreign_key
 * `timestamp` - timestamp
 * `measure` - measure
 * `dimension` - dimension
 * `monetary` - monetary
 * `free_text` - free_text
 * `enum` - enum
 * `uuid` - uuid
 * `unknown` - unknown
 */
export type SemanticTypeEnumApi = (typeof SemanticTypeEnumApi)[keyof typeof SemanticTypeEnumApi]

export const SemanticTypeEnumApi = {
    EntityId: 'entity_id',
    ForeignKey: 'foreign_key',
    Timestamp: 'timestamp',
    Measure: 'measure',
    Dimension: 'dimension',
    Monetary: 'monetary',
    FreeText: 'free_text',
    Enum: 'enum',
    Uuid: 'uuid',
    Unknown: 'unknown',
} as const

/**
 * * `pii` - pii
 * `sensitive` - sensitive
 * `public` - public
 * `unknown` - unknown
 */
export type PiiClassEnumApi = (typeof PiiClassEnumApi)[keyof typeof PiiClassEnumApi]

export const PiiClassEnumApi = {
    Pii: 'pii',
    Sensitive: 'sensitive',
    Public: 'public',
    Unknown: 'unknown',
} as const

/**
 * Body for catalog-columns-create. Identified by (node_id, name).
 */
export interface UpsertColumnInputApi {
    /** ID of the parent CatalogNode (returned by catalog-nodes-create). */
    node_id: string
    /**
     * Column name as it appears in the underlying table. Case-sensitive. Combined with `node_id` to form the upsert key — calling create again with the same (node_id, name) updates in place.
     * @maxLength 400
     */
    name: string
    /** Ordinal position of the column in the source table. Used for display and stable iteration. */
    position?: number
    /**
     * Raw ClickHouse type string (`String`, `Nullable(DateTime64(3))`, `Array(String)`...). Set when the column comes from a ClickHouse-backed table; null for Postgres-only sources.
     * @maxLength 255
     * @nullable
     */
    clickhouse_type?: string | null
    /**
     * HogQL-normalized type — `String`, `Int`, `Float`, `Boolean`, `DateTime`, `Array`, `JSON`. What the agent sees when reading via `system.columns`. Inferred from clickhouse_type when not set explicitly.
     * @maxLength 128
     * @nullable
     */
    hogql_type?: string | null
    /** Whether the column can hold NULL values. Drives null-handling guidance in generated queries. */
    nullable?: boolean
    /**
     * What the column represents in business terms — meaning, units, valid values, gotchas. Example: "Subscription monthly recurring revenue in USD cents. Excludes refunds. Null for one-time charges."
     * @nullable
     */
    synthetic_description?: string | null
    /** Role of the column for query planning. `entity_id` for primary identifiers, `foreign_key` for join targets, `timestamp` for time filtering, `measure` for aggregation, `dimension` for group-by, `monetary` for currency, `free_text` for unstructured prose, `enum` for closed value sets.

  * `entity_id` - entity_id
  * `foreign_key` - foreign_key
  * `timestamp` - timestamp
  * `measure` - measure
  * `dimension` - dimension
  * `monetary` - monetary
  * `free_text` - free_text
  * `enum` - enum
  * `uuid` - uuid
  * `unknown` - unknown */
    semantic_type?: SemanticTypeEnumApi | null
    /** Sensitivity classification. `pii` for personally identifiable (email, name, IP), `sensitive` for business-confidential, `public` for safe-to-export, `unknown` to defer classification.

  * `pii` - pii
  * `sensitive` - sensitive
  * `public` - public
  * `unknown` - unknown */
    pii_class?: PiiClassEnumApi | null
    /**
     * Model that generated the description/typing — same convention as on nodes.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
    /**
     * Agent confidence (0..1) in the description and semantic typing.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

export interface CatalogColumnDTOApi {
    id: string
    name: string
    position: number
    /** @nullable */
    clickhouse_type: string | null
    /** @nullable */
    hogql_type: string | null
    nullable: boolean
    /** @nullable */
    description: string | null
    /** @nullable */
    semantic_type: string | null
    /** @nullable */
    pii_class: string | null
    /** @nullable */
    confidence: number | null
}

/**
 * Body for catalog-columns-partial-update. Every field optional.
 */
export interface PatchedUpdateColumnInputApi {
    /**
     * What the column represents in business terms — meaning, units, valid values, gotchas.
     * @nullable
     */
    synthetic_description?: string | null
    /** Role of the column for query planning. See create endpoint for full semantics.

  * `entity_id` - entity_id
  * `foreign_key` - foreign_key
  * `timestamp` - timestamp
  * `measure` - measure
  * `dimension` - dimension
  * `monetary` - monetary
  * `free_text` - free_text
  * `enum` - enum
  * `uuid` - uuid
  * `unknown` - unknown */
    semantic_type?: SemanticTypeEnumApi | null
    /** Sensitivity classification. `pii`, `sensitive`, `public`, or `unknown`.

  * `pii` - pii
  * `sensitive` - sensitive
  * `public` - public
  * `unknown` - unknown */
    pii_class?: PiiClassEnumApi | null
    /**
     * Agent confidence (0..1) in the description and semantic typing.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

export interface CatalogNodeDTOApi {
    columns: CatalogColumnDTOApi[]
    id: string
    team_id: number
    kind: string
    name: string
    /** @nullable */
    description: string | null
    /** @nullable */
    semantic_role: string | null
    /** @nullable */
    business_domain: string | null
    tags: string[]
    /** @nullable */
    first_seen_at: string | null
    /** @nullable */
    last_seen_at: string | null
    /** @nullable */
    last_traversed_at: string | null
    /** @nullable */
    confidence: number | null
    status: string
    /** @nullable */
    reviewed_at: string | null
}

export interface PaginatedCatalogNodeDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CatalogNodeDTOApi[]
}

/**
 * * `warehouse_table` - warehouse_table
 * `saved_query` - saved_query
 * `system_table` - system_table
 * `posthog_table` - posthog_table
 */
export type UpsertNodeInputKindEnumApi = (typeof UpsertNodeInputKindEnumApi)[keyof typeof UpsertNodeInputKindEnumApi]

export const UpsertNodeInputKindEnumApi = {
    WarehouseTable: 'warehouse_table',
    SavedQuery: 'saved_query',
    SystemTable: 'system_table',
    PosthogTable: 'posthog_table',
} as const

/**
 * Body for catalog-nodes-create. team_id is taken from the URL, not the body.
 */
export interface UpsertNodeInputApi {
    /** What kind of catalog entry this is. `warehouse_table` for an imported data warehouse table, `saved_query` for a derived view, `system_table` for a built-in PostHog system table like `events` or `persons`, `posthog_table` for other first-party tables.

  * `warehouse_table` - warehouse_table
  * `saved_query` - saved_query
  * `system_table` - system_table
  * `posthog_table` - posthog_table */
    kind: UpsertNodeInputKindEnumApi
    /**
     * Stable identifier for the node, unique per (team, kind). For warehouse tables this is the imported table name (e.g. `stripe_charges`). For system tables use the canonical name (e.g. `events`). The agent looks nodes up by name before upserting, so keep this stable across runs.
     * @maxLength 400
     */
    name: string
    /**
     * Set when `kind=warehouse_table` to bind this node to the backing `DataWarehouseTable` row. Used for cascade cleanup when the warehouse table is deleted. Leave null for system/posthog tables.
     * @nullable
     */
    warehouse_table_id?: string | null
    /**
     * Set when `kind=saved_query` to bind this node to the backing `DataWarehouseSavedQuery` row. Leave null for non-saved-query kinds.
     * @nullable
     */
    saved_query_id?: string | null
    /**
     * Markdown description of what this table contains, when to use it, caveats, and how it relates to other tables. Written by the agent or human. Becomes the primary signal future agent runs use to pick the right table for a question.
     * @nullable
     */
    synthetic_description?: string | null
    /**
     * Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`, `event_source`, `identity`. Helps the agent reason about join cardinality and aggregation safety.
     * @maxLength 64
     * @nullable
     */
    semantic_role?: string | null
    /**
     * Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`. Used to group related tables in discovery and to scope cross-source queries.
     * @maxLength 64
     * @nullable
     */
    business_domain?: string | null
    /** Free-form tags for filtering and grouping. Lowercase, short. Examples: `pii`, `derived`, `incremental`, `stripe`, `canonical`. */
    tags?: string[]
    /**
     * Identifier of the model that produced this row when generated by an agent — e.g. `claude-opus-4-7`. Leave null when humans author the description. Used for auditing autofill quality over time.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
    /**
     * Agent's confidence (0..1) in the description and semantic tagging it just wrote. Surfaces as a draft/confirmed indicator and lets review workflows prioritize low-confidence rows.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

/**
 * * `proposed` - proposed
 * `approved` - approved
 * `official` - official
 * `drift` - drift
 */
export type UpdateNodeInputStatusEnumApi =
    (typeof UpdateNodeInputStatusEnumApi)[keyof typeof UpdateNodeInputStatusEnumApi]

export const UpdateNodeInputStatusEnumApi = {
    Proposed: 'proposed',
    Approved: 'approved',
    Official: 'official',
    Drift: 'drift',
} as const

/**
 * Body for catalog-nodes-partial-update. Every field optional; only supplied fields are written.
 */
export interface PatchedUpdateNodeInputApi {
    /**
     * Rename the node. Must remain unique per (team, kind). Avoid renaming once agents have linked to it.
     * @maxLength 400
     */
    name?: string
    /**
     * Markdown description of what this table contains, when to use it, caveats, and how it relates to other tables. Becomes the primary signal future agent runs use to pick the right table.
     * @nullable
     */
    synthetic_description?: string | null
    /**
     * Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`.
     * @maxLength 64
     * @nullable
     */
    semantic_role?: string | null
    /**
     * Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`.
     * @maxLength 64
     * @nullable
     */
    business_domain?: string | null
    /** Free-form lowercase tags. Replaces the existing tag list when supplied. */
    tags?: string[]
    /**
     * Agent confidence (0..1). Humans can override or clear to mark the row as verified.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** Review state. `proposed` for AI-authored / unreviewed, `approved` once a human has confirmed it, `official` for canonical definitions, `drift` when the agent detects schema or semantic drift.

  * `proposed` - proposed
  * `approved` - approved
  * `official` - official
  * `drift` - drift */
    status?: UpdateNodeInputStatusEnumApi
}

export interface CatalogRelationshipDTOApi {
    id: string
    source_node_id: string
    /** @nullable */
    source_column: string | null
    target_node_id: string
    /** @nullable */
    target_column: string | null
    kind: string
    confidence: number
    reasoning: string
    status: string
    discovered_at: string
    last_seen_at: string
}

/**
 * Bundles nodes and relationships for the graph view. Drives the React Flow scene
so the client can render the whole topology in one fetch.
 */
export interface CatalogGraphDTOApi {
    readonly nodes: readonly CatalogNodeDTOApi[]
    readonly relationships: readonly CatalogRelationshipDTOApi[]
    /** @nullable */
    generated_at?: string | null
}

/**
 * * `foreign_key` - foreign_key
 * `same_entity` - same_entity
 * `lineage` - lineage
 * `declared_join` - declared_join
 * `join_candidate` - join_candidate
 */
export type ProposeRelationshipInputKindEnumApi =
    (typeof ProposeRelationshipInputKindEnumApi)[keyof typeof ProposeRelationshipInputKindEnumApi]

export const ProposeRelationshipInputKindEnumApi = {
    ForeignKey: 'foreign_key',
    SameEntity: 'same_entity',
    Lineage: 'lineage',
    DeclaredJoin: 'declared_join',
    JoinCandidate: 'join_candidate',
} as const

/**
 * Body for catalog-relationships-create. Always lands in PROPOSED status until reviewed.
 */
export interface ProposeRelationshipInputApi {
    /** ID of the node the relationship originates from — e.g. the fact table, source side of a join. */
    source_node_id: string
    /** ID of the node the relationship points to. For joins this is the other table; for foreign keys, the referenced table. */
    target_node_id: string
    /** Relationship type. `foreign_key` when the source column references a target PK. `same_entity` when two columns identify the same business object (Stripe.customer_id ≈ Postgres.users.id). `lineage` when the target table is derived from the source. `declared_join` for an officially supported join. `join_candidate` for an inferred-but-unconfirmed join.

  * `foreign_key` - foreign_key
  * `same_entity` - same_entity
  * `lineage` - lineage
  * `declared_join` - declared_join
  * `join_candidate` - join_candidate */
    kind: ProposeRelationshipInputKindEnumApi
    /**
     * Agent's confidence (0..1) that this relationship is correct. Drives the review queue — low-confidence edges surface for human approval before agents trust them for joins.
     * @minimum 0
     * @maximum 1
     */
    confidence: number
    /**
     * Narrows the source side to a specific column. Set for foreign-key and join edges; null for table-level lineage.
     * @nullable
     */
    source_column_id?: string | null
    /**
     * Narrows the target side to a specific column. Same semantics as source_column_id.
     * @nullable
     */
    target_column_id?: string | null
    /** Free-text justification for the proposal — the data points or column-name signals the agent used. Surfaces in the review UI so a human can decide whether to accept or reject. */
    reasoning?: string
    /**
     * ID of the CatalogTraversalRun this relationship was discovered in. Leave null for ad-hoc proposals.
     * @nullable
     */
    discovered_in_run_id?: string | null
    /**
     * Model that proposed the relationship — same convention as on nodes and columns.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
}

/**
 * * `proposed` - proposed
 * `accepted` - accepted
 * `rejected` - rejected
 * `stale` - stale
 */
export type UpdateRelationshipInputStatusEnumApi =
    (typeof UpdateRelationshipInputStatusEnumApi)[keyof typeof UpdateRelationshipInputStatusEnumApi]

export const UpdateRelationshipInputStatusEnumApi = {
    Proposed: 'proposed',
    Accepted: 'accepted',
    Rejected: 'rejected',
    Stale: 'stale',
} as const

/**
 * Body for catalog-relationships-partial-update. Used by reviewers to accept/reject proposals.
 */
export interface PatchedUpdateRelationshipInputApi {
    /** Review state. `proposed` is the initial state, `accepted` once a human confirms the edge, `rejected` to dismiss it, `stale` when the underlying schema has moved on.

  * `proposed` - proposed
  * `accepted` - accepted
  * `rejected` - rejected
  * `stale` - stale */
    status?: UpdateRelationshipInputStatusEnumApi
    /**
     * Reviewer's confidence (0..1) in the edge after manual inspection.
     * @minimum 0
     * @maximum 1
     */
    confidence?: number
    /** Free-text justification, typically extended during human review. */
    reasoning?: string
}

export type CatalogNodesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
