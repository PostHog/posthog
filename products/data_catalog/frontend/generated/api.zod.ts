/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Trust marks on warehouse tables and views. Reads exclude soft-deleted targets.
 */
export const DataCatalogCertificationsCreateBody = /* @__PURE__ */ zod
    .object({
        table_id: zod.uuid().optional().describe('Warehouse table id to certify (XOR the other targets).'),
        saved_query_id: zod.uuid().optional().describe('Warehouse view (saved query) id to certify.'),
        table_name: zod.string().optional().describe('Table name; 409 with candidates if ambiguous.'),
        view_name: zod.string().optional().describe('View name; 409 with candidates if ambiguous.'),
        notes: zod.string().optional().describe('Why this mark exists.'),
    })
    .describe('Input for proposing a certification: address the target by id or (convenience) by name.')

/**
 * Create a metric, or refine the one already holding this name for the team.
 */
export const dataCatalogMetricsCreateBodyNameMax = 128

export const dataCatalogMetricsCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataCatalogMetricsCreateBodyDisplayNameMax = 255

export const dataCatalogMetricsCreateBodyUnitMax = 64

export const dataCatalogMetricsCreateBodySourceInsightShortIdMax = 12

export const dataCatalogMetricsCreateBodyAiModelMax = 128

export const DataCatalogMetricsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataCatalogMetricsCreateBodyNameMax)
        .regex(dataCatalogMetricsCreateBodyNameRegExp)
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricsCreateBodyDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricsCreateBodyUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricsCreateBodySourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    created_source: zod
        .enum(['user', 'ai_generated'])
        .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
        .optional()
        .describe(
            "Whether a human ('user') or an agent ('ai_generated') authored this metric.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
        ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricsCreateBodyAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod.number().nullish().describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsUpdateBodyNameMax = 128

export const dataCatalogMetricsUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataCatalogMetricsUpdateBodyDisplayNameMax = 255

export const dataCatalogMetricsUpdateBodyUnitMax = 64

export const dataCatalogMetricsUpdateBodySourceInsightShortIdMax = 12

export const dataCatalogMetricsUpdateBodyAiModelMax = 128

export const DataCatalogMetricsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataCatalogMetricsUpdateBodyNameMax)
        .regex(dataCatalogMetricsUpdateBodyNameRegExp)
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricsUpdateBodyDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricsUpdateBodyUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricsUpdateBodySourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    created_source: zod
        .enum(['user', 'ai_generated'])
        .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
        .optional()
        .describe(
            "Whether a human ('user') or an agent ('ai_generated') authored this metric.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
        ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricsUpdateBodyAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod.number().nullish().describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * CRUD for catalog metrics, addressed by their reserved ``name`` (e.g. /metrics/mrr/).
 */
export const dataCatalogMetricsPartialUpdateBodyNameMax = 128

export const dataCatalogMetricsPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataCatalogMetricsPartialUpdateBodyDisplayNameMax = 255

export const dataCatalogMetricsPartialUpdateBodyUnitMax = 64

export const dataCatalogMetricsPartialUpdateBodySourceInsightShortIdMax = 12

export const dataCatalogMetricsPartialUpdateBodyAiModelMax = 128

export const DataCatalogMetricsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyNameMax)
        .regex(dataCatalogMetricsPartialUpdateBodyNameRegExp)
        .optional()
        .describe('Identifier-safe run handle, unique per team and reserved forever. Write-once.'),
    display_name: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyDisplayNameMax)
        .optional()
        .describe('Human-friendly label. Mutable, unlike name.'),
    description: zod.string().optional().describe('What the metric means and how to interpret it.'),
    unit: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyUnitMax)
        .optional()
        .describe('Unit of the result, e.g. usd, percent, cents.'),
    definition: zod
        .record(zod.string(), zod.unknown())
        .nullish()
        .describe('Machine-readable query. Omit for a name+description-only stub. Stored upgrade-canonical.'),
    source_insight_short_id: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodySourceInsightShortIdMax)
        .nullish()
        .describe(
            "Create the metric from this insight's query (snapshotted server-side). Set to null to unlink. Mutually exclusive with definition."
        ),
    created_source: zod
        .enum(['user', 'ai_generated'])
        .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
        .optional()
        .describe(
            "Whether a human ('user') or an agent ('ai_generated') authored this metric.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
        ),
    ai_model: zod
        .string()
        .max(dataCatalogMetricsPartialUpdateBodyAiModelMax)
        .optional()
        .describe('Model that generated the metric, if AI-authored.'),
    confidence: zod.number().nullish().describe("AI author's confidence in the proposal, 0-1."),
    reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
})

/**
 * Execute the metric's definition and return the normalized result envelope.
 */
export const DataCatalogMetricsRunCreateBody = /* @__PURE__ */ zod
    .object({
        date_from: zod
            .string()
            .optional()
            .describe(
                "Override the start of the query window (e.g. '-7d'). Rejected for HogQLQuery metrics, whose window is fixed in SQL."
            ),
        date_to: zod.string().optional().describe('Override the end of the query window.'),
        interval: zod
            .enum(['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'])
            .describe(
                '\* `second` - second\n\* `minute` - minute\n\* `hour` - hour\n\* `day` - day\n\* `week` - week\n\* `month` - month\n\* `quarter` - quarter\n\* `year` - year'
            )
            .optional()
            .describe(
                'Override the bucket interval. Rejected for HogQLQuery metrics.\n\n\* `second` - second\n\* `minute` - minute\n\* `hour` - hour\n\* `day` - day\n\* `week` - week\n\* `month` - month\n\* `quarter` - quarter\n\* `year` - year'
            ),
        query_id: zod.string().optional().describe('Client-supplied id to correlate or cancel the run.'),
    })
    .describe('Optional run-time overrides. The whole body may be omitted; a metric runs by its URL name.')
