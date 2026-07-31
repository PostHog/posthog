/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const RoleAtOrganizationEnumApi = zod
    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
    .describe(
        '\* `engineering` - Engineering\n\* `data` - Data\n\* `product` - Product Management\n\* `founder` - Founder\n\* `leadership` - Leadership\n\* `marketing` - Marketing\n\* `sales` - Sales \/ Success\n\* `other` - Other'
    )

export type RoleAtOrganizationEnumApi = zod.input<typeof RoleAtOrganizationEnumApi>
export type RoleAtOrganizationEnumApiOutput = zod.output<typeof RoleAtOrganizationEnumApi>

export const BlankEnumApi = zod.enum([''])

export type BlankEnumApi = zod.input<typeof BlankEnumApi>
export type BlankEnumApiOutput = zod.output<typeof BlankEnumApi>

export const userBasicApiDistinctIdMax = 200

export const userBasicApiFirstNameMax = 150

export const userBasicApiLastNameMax = 150

export const userBasicApiEmailMax = 254

export const UserBasicApi = zod.object({
    id: zod.number(),
    uuid: zod.uuid(),
    distinct_id: zod.string().max(userBasicApiDistinctIdMax).nullish(),
    first_name: zod.string().max(userBasicApiFirstNameMax).optional(),
    last_name: zod.string().max(userBasicApiLastNameMax).optional(),
    email: zod.email().max(userBasicApiEmailMax),
    is_email_verified: zod.boolean().nullish(),
    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
    role_at_organization: zod.union([RoleAtOrganizationEnumApi, BlankEnumApi, zod.null()]).optional(),
})

export type UserBasicApi = zod.input<typeof UserBasicApi>
export type UserBasicApiOutput = zod.output<typeof UserBasicApi>

export const DataCatalogCertificationApi = zod.object({
    id: zod.uuid(),
    table: zod.uuid().nullable().describe('The warehouse table this mark applies to (XOR saved_query).'),
    saved_query: zod.uuid().nullable().describe('The warehouse view this mark applies to (XOR table).'),
    target_type: zod.string().describe("Whether the marked target is a 'table' or a 'view'."),
    target_name: zod.string().describe('Name of the marked table or view.'),
    status: zod.string().describe('proposed, certified (prefer this source), or deprecated (avoid this source).'),
    notes: zod.string().optional().describe("Why this mark exists, e.g. 'canonical MRR source'."),
    certified_by: zod.union([UserBasicApi, zod.null()]).describe('User who last set certified\/deprecated, or null.'),
    certified_at: zod.iso.datetime({ offset: true }).nullable(),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type DataCatalogCertificationApi = zod.input<typeof DataCatalogCertificationApi>
export type DataCatalogCertificationApiOutput = zod.output<typeof DataCatalogCertificationApi>

export const PaginatedDataCatalogCertificationListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DataCatalogCertificationApi),
})

export type PaginatedDataCatalogCertificationListApi = zod.input<typeof PaginatedDataCatalogCertificationListApi>
export type PaginatedDataCatalogCertificationListApiOutput = zod.output<typeof PaginatedDataCatalogCertificationListApi>

export const CertificationCreateApi = zod
    .object({
        table_id: zod.uuid().optional().describe('Warehouse table id to certify (XOR the other targets).'),
        saved_query_id: zod.uuid().optional().describe('Warehouse view (saved query) id to certify.'),
        table_name: zod.string().optional().describe('Table name; 409 with candidates if ambiguous.'),
        view_name: zod.string().optional().describe('View name; 409 with candidates if ambiguous.'),
        notes: zod.string().optional().describe('Why this mark exists.'),
    })
    .describe('Input for proposing a certification: address the target by id or (convenience) by name.')

export type CertificationCreateApi = zod.input<typeof CertificationCreateApi>
export type CertificationCreateApiOutput = zod.output<typeof CertificationCreateApi>

export const CreatedSourceEnumApi = zod
    .enum(['user', 'ai_generated'])
    .describe('\* `user` - user\n\* `ai_generated` - ai_generated')

export type CreatedSourceEnumApi = zod.input<typeof CreatedSourceEnumApi>
export type CreatedSourceEnumApiOutput = zod.output<typeof CreatedSourceEnumApi>

export const dataCatalogMetricApiNameMax = 128

export const dataCatalogMetricApiNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataCatalogMetricApiDisplayNameMax = 255

export const dataCatalogMetricApiUnitMax = 64

export const dataCatalogMetricApiSourceInsightShortIdMax = 12

export const dataCatalogMetricApiAiModelMax = 128

export const dataCatalogMetricApiConfidenceMin = 0
export const dataCatalogMetricApiConfidenceMax = 1

export const DataCatalogMetricApi = zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(dataCatalogMetricApiNameMax)
        .regex(dataCatalogMetricApiNameRegExp)
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricApiDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricApiUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    owner: zod.string().nullable().describe('Email of the human accountable for this metric, or null.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    definition_kind: zod
        .string()
        .nullable()
        .describe('Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.'),
    referenced_table_names: zod
        .unknown()
        .describe(
            "Tables the definition directly references, extracted at write time for the catalog's denied-table filter."
        ),
    status: zod.string().describe("Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately."),
    is_drifted: zod
        .boolean()
        .describe('True when the definition has drifted from its linked source insight (or the insight is gone).'),
    approved_at: zod.iso.datetime({ offset: true }).nullable(),
    approved_by: zod.union([UserBasicApi, zod.null()]).describe('User who approved this metric as canonical, or null.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricApiSourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    last_run_at: zod.iso
        .datetime({ offset: true })
        .nullable()
        .describe('When the metric was last run (30-minute throttle).'),
    created_source: CreatedSourceEnumApi.optional().describe(
        "Whether a human ('user') or an agent ('ai_generated') authored this metric.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
    ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricApiAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod
        .number()
        .min(dataCatalogMetricApiConfidenceMin)
        .max(dataCatalogMetricApiConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    created_by: UserBasicApi.describe('User who first created this metric.'),
    created_at: zod.iso.datetime({ offset: true }),
    updated_at: zod.iso.datetime({ offset: true }).nullable(),
})

export type DataCatalogMetricApi = zod.input<typeof DataCatalogMetricApi>
export type DataCatalogMetricApiOutput = zod.output<typeof DataCatalogMetricApi>

export const PaginatedDataCatalogMetricListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DataCatalogMetricApi),
})

export type PaginatedDataCatalogMetricListApi = zod.input<typeof PaginatedDataCatalogMetricListApi>
export type PaginatedDataCatalogMetricListApiOutput = zod.output<typeof PaginatedDataCatalogMetricListApi>

export const patchedDataCatalogMetricApiNameMax = 128

export const patchedDataCatalogMetricApiNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const patchedDataCatalogMetricApiDisplayNameMax = 255

export const patchedDataCatalogMetricApiUnitMax = 64

export const patchedDataCatalogMetricApiSourceInsightShortIdMax = 12

export const patchedDataCatalogMetricApiAiModelMax = 128

export const patchedDataCatalogMetricApiConfidenceMin = 0
export const patchedDataCatalogMetricApiConfidenceMax = 1

export const PatchedDataCatalogMetricApi = zod.object({
    id: zod.uuid().optional(),
    name: zod
        .string()
        .max(patchedDataCatalogMetricApiNameMax)
        .regex(patchedDataCatalogMetricApiNameRegExp)
        .optional()
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(patchedDataCatalogMetricApiDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().optional().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(patchedDataCatalogMetricApiUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    owner: zod.string().nullish().describe('Email of the human accountable for this metric, or null.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    definition_kind: zod
        .string()
        .nullish()
        .describe('Query kind of the definition (HogQLQuery, TrendsQuery, ...), or null for a stub.'),
    referenced_table_names: zod
        .unknown()
        .optional()
        .describe(
            "Tables the definition directly references, extracted at write time for the catalog's denied-table filter."
        ),
    status: zod
        .string()
        .optional()
        .describe("Persisted lifecycle state: 'proposed' or 'approved'. Drift is reported separately."),
    is_drifted: zod
        .boolean()
        .optional()
        .describe('True when the definition has drifted from its linked source insight (or the insight is gone).'),
    approved_at: zod.iso.datetime({ offset: true }).nullish(),
    approved_by: zod
        .union([UserBasicApi, zod.null()])
        .optional()
        .describe('User who approved this metric as canonical, or null.'),
    source_insight_short_id: zod
        .string()
        .max(patchedDataCatalogMetricApiSourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    last_run_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('When the metric was last run (30-minute throttle).'),
    created_source: CreatedSourceEnumApi.optional().describe(
        "Whether a human ('user') or an agent ('ai_generated') authored this metric.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
    ),
    ai_model: zod
        .string()
        .max(patchedDataCatalogMetricApiAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod
        .number()
        .min(patchedDataCatalogMetricApiConfidenceMin)
        .max(patchedDataCatalogMetricApiConfidenceMax)
        .nullish()
        .describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    created_by: UserBasicApi.optional().describe('User who first created this metric.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    updated_at: zod.iso.datetime({ offset: true }).nullish(),
})

export type PatchedDataCatalogMetricApi = zod.input<typeof PatchedDataCatalogMetricApi>
export type PatchedDataCatalogMetricApiOutput = zod.output<typeof PatchedDataCatalogMetricApi>

export const DataCatalogMetricRunRequestIntervalEnumApi = zod
    .enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])
    .describe(
        '\* `second` - second\n\* `minute` - minute\n\* `hour` - hour\n\* `day` - day\n\* `week` - week\n\* `month` - month\n\* `quarter` - quarter\n\* `year` - year'
    )

export type DataCatalogMetricRunRequestIntervalEnumApi = zod.input<typeof DataCatalogMetricRunRequestIntervalEnumApi>
export type DataCatalogMetricRunRequestIntervalEnumApiOutput = zod.output<
    typeof DataCatalogMetricRunRequestIntervalEnumApi
>

export const DataCatalogMetricRunRequestApi = zod
    .object({
        date_from: zod
            .string()
            .optional()
            .describe(
                "Override the start of the query window (e.g. '-7d'). Rejected for HogQLQuery metrics, whose window is fixed in SQL."
            ),
        date_to: zod.string().optional().describe('Override the end of the query window.'),
        interval: DataCatalogMetricRunRequestIntervalEnumApi.optional().describe(
            'Override the bucket interval. Rejected for HogQLQuery metrics.\n\n\* `second` - second\n\* `minute` - minute\n\* `hour` - hour\n\* `day` - day\n\* `week` - week\n\* `month` - month\n\* `quarter` - quarter\n\* `year` - year'
        ),
        query_id: zod.string().optional().describe('Client-supplied id to correlate or cancel the run.'),
    })
    .describe('Optional run-time overrides. The whole body may be omitted; a metric runs by its URL name.')

export type DataCatalogMetricRunRequestApi = zod.input<typeof DataCatalogMetricRunRequestApi>
export type DataCatalogMetricRunRequestApiOutput = zod.output<typeof DataCatalogMetricRunRequestApi>

export const DataCatalogMetricRunApi = zod
    .object({
        status: zod.string().describe('Lifecycle state of the metric that produced these results.'),
        is_drifted: zod
            .boolean()
            .describe(
                "True when the definition has drifted from its linked source insight (or the insight is gone). Only status 'approved' with is_drifted false is canonical."
            ),
        unit: zod.string().nullable().describe('Unit of the result, e.g. usd, percent.'),
        kind: zod.string().nullable().describe('Query kind that was executed.'),
        results: zod.unknown().describe('The query results, for an executable metric. Null for a markdown metric.'),
        compiled_query: zod.string().nullable().describe('The compiled HogQL, when available.'),
        query_status: zod.unknown().describe('Async query status, when the run is not blocking.'),
        posthog_url: zod
            .string()
            .nullable()
            .describe('Deep link to open the query in the app (SQL editor or insight).'),
        instructions: zod
            .string()
            .nullable()
            .describe(
                'For a markdown (agent-calculated) metric, the steps to follow to compute it. Null for an executable metric.'
            ),
    })
    .describe('Normalized envelope returned by the metric-run endpoint.')

export type DataCatalogMetricRunApi = zod.input<typeof DataCatalogMetricRunApi>
export type DataCatalogMetricRunApiOutput = zod.output<typeof DataCatalogMetricRunApi>

export const dataCatalogRelationshipProposalApiSourceTableNameMax = 400

export const dataCatalogRelationshipProposalApiSourceTableKeyMax = 400

export const dataCatalogRelationshipProposalApiJoiningTableNameMax = 400

export const dataCatalogRelationshipProposalApiJoiningTableKeyMax = 400

export const dataCatalogRelationshipProposalApiFieldNameMax = 400

export const dataCatalogRelationshipProposalApiConfidenceMin = 0
export const dataCatalogRelationshipProposalApiConfidenceMax = 1

export const DataCatalogRelationshipProposalApi = zod.object({
    id: zod.uuid(),
    source_table_name: zod
        .string()
        .max(dataCatalogRelationshipProposalApiSourceTableNameMax)
        .describe('Name of the table the join starts from.'),
    source_table_key: zod
        .string()
        .max(dataCatalogRelationshipProposalApiSourceTableKeyMax)
        .describe('HogQL key expression on the source table (casts allowed).'),
    joining_table_name: zod
        .string()
        .max(dataCatalogRelationshipProposalApiJoiningTableNameMax)
        .describe('Name of the table being joined in.'),
    joining_table_key: zod
        .string()
        .max(dataCatalogRelationshipProposalApiJoiningTableKeyMax)
        .describe('HogQL key expression on the joining table (casts allowed).'),
    field_name: zod
        .string()
        .max(dataCatalogRelationshipProposalApiFieldNameMax)
        .describe('Accessor the join adds to the source table.'),
    configuration: zod.unknown().optional().describe('Extra join configuration, e.g. a field mapping.'),
    confidence: zod
        .number()
        .min(dataCatalogRelationshipProposalApiConfidenceMin)
        .max(dataCatalogRelationshipProposalApiConfidenceMax)
        .nullish()
        .describe('Discovery confidence in this join, 0-1.'),
    reasoning: zod.string().optional().describe('Why this join is proposed.'),
    evidence: zod.unknown().optional().describe('Sampling evidence: match rates, sample values.'),
    status: zod.string().describe('proposed, accepted (promoted to a real join), or rejected (never re-proposed).'),
    reviewed_by: zod.union([UserBasicApi, zod.null()]).describe('User who accepted or rejected the proposal.'),
    reviewed_at: zod.iso.datetime({ offset: true }).nullable(),
    rejection_reason: zod.string().describe('Why the proposal was rejected.'),
    created_join: zod
        .uuid()
        .nullable()
        .describe('The join created when this proposal was accepted (promotion provenance).'),
    created_by: zod.number().nullable(),
    created_at: zod.iso.datetime({ offset: true }),
})

export type DataCatalogRelationshipProposalApi = zod.input<typeof DataCatalogRelationshipProposalApi>
export type DataCatalogRelationshipProposalApiOutput = zod.output<typeof DataCatalogRelationshipProposalApi>

export const PaginatedDataCatalogRelationshipProposalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(DataCatalogRelationshipProposalApi),
})

export type PaginatedDataCatalogRelationshipProposalListApi = zod.input<
    typeof PaginatedDataCatalogRelationshipProposalListApi
>
export type PaginatedDataCatalogRelationshipProposalListApiOutput = zod.output<
    typeof PaginatedDataCatalogRelationshipProposalListApi
>

export const RelationshipRejectApi = zod.object({
    rejection_reason: zod
        .string()
        .optional()
        .describe('Why the proposal is rejected. Persisted so it is never re-proposed.'),
})

export type RelationshipRejectApi = zod.input<typeof RelationshipRejectApi>
export type RelationshipRejectApiOutput = zod.output<typeof RelationshipRejectApi>
