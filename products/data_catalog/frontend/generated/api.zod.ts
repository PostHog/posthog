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
 * Create a metric, or refine the one already holding this name for the team.
 */
export const dataCatalogMetricsCreateBodyNameMax = 128

export const dataCatalogMetricsCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataCatalogMetricsCreateBodyDisplayNameMax = 255

export const dataCatalogMetricsCreateBodyUnitMax = 64

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
