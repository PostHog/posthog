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
 * Run the named checks now, or every enabled check in the project when none are named. Returns the suite run to poll for the report.
 */
export const DataQualityRunsCreateBody = /* @__PURE__ */ zod
    .object({
        check_ids: zod
            .array(zod.uuid())
            .optional()
            .describe('Ids of the checks to run. Omit to run every enabled check in the project.'),
    })
    .describe('What to run in a project-wide suite run.')

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const warehouseSavedQueriesChecksCreateBodyNameMax = 128

export const warehouseSavedQueriesChecksCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseSavedQueriesChecksCreateBodyColumnNameMax = 400

export const warehouseSavedQueriesChecksCreateBodyAiModelMax = 128

export const warehouseSavedQueriesChecksCreateBodyConfidenceMin = 0
export const warehouseSavedQueriesChecksCreateBodyConfidenceMax = 1

export const WarehouseSavedQueriesChecksCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyNameMax)
            .regex(warehouseSavedQueriesChecksCreateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseSavedQueriesChecksCreateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseSavedQueriesChecksCreateBodyConfidenceMin)
            .max(warehouseSavedQueriesChecksCreateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseSavedQueriesChecksUpdateBodyNameMax = 128

export const warehouseSavedQueriesChecksUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseSavedQueriesChecksUpdateBodyColumnNameMax = 400

export const warehouseSavedQueriesChecksUpdateBodyAiModelMax = 128

export const warehouseSavedQueriesChecksUpdateBodyConfidenceMin = 0
export const warehouseSavedQueriesChecksUpdateBodyConfidenceMax = 1

export const WarehouseSavedQueriesChecksUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesChecksUpdateBodyNameMax)
            .regex(warehouseSavedQueriesChecksUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseSavedQueriesChecksUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseSavedQueriesChecksUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseSavedQueriesChecksUpdateBodyConfidenceMin)
            .max(warehouseSavedQueriesChecksUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseSavedQueriesChecksPartialUpdateBodyNameMax = 128

export const warehouseSavedQueriesChecksPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseSavedQueriesChecksPartialUpdateBodyColumnNameMax = 400

export const warehouseSavedQueriesChecksPartialUpdateBodyAiModelMax = 128

export const warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMin = 0
export const warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMax = 1

export const WarehouseSavedQueriesChecksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyNameMax)
            .regex(warehouseSavedQueriesChecksPartialUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .optional()
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseSavedQueriesChecksPartialUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMin)
            .max(warehouseSavedQueriesChecksPartialUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Create a check on this table or view, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const warehouseTablesChecksCreateBodyNameMax = 128

export const warehouseTablesChecksCreateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseTablesChecksCreateBodyColumnNameMax = 400

export const warehouseTablesChecksCreateBodyAiModelMax = 128

export const warehouseTablesChecksCreateBodyConfidenceMin = 0
export const warehouseTablesChecksCreateBodyConfidenceMax = 1

export const WarehouseTablesChecksCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseTablesChecksCreateBodyNameMax)
            .regex(warehouseTablesChecksCreateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseTablesChecksCreateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseTablesChecksCreateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseTablesChecksCreateBodyConfidenceMin)
            .max(warehouseTablesChecksCreateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseTablesChecksUpdateBodyNameMax = 128

export const warehouseTablesChecksUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseTablesChecksUpdateBodyColumnNameMax = 400

export const warehouseTablesChecksUpdateBodyAiModelMax = 128

export const warehouseTablesChecksUpdateBodyConfidenceMin = 0
export const warehouseTablesChecksUpdateBodyConfidenceMax = 1

export const WarehouseTablesChecksUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseTablesChecksUpdateBodyNameMax)
            .regex(warehouseTablesChecksUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseTablesChecksUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseTablesChecksUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseTablesChecksUpdateBodyConfidenceMin)
            .max(warehouseTablesChecksUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The table or view it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const warehouseTablesChecksPartialUpdateBodyNameMax = 128

export const warehouseTablesChecksPartialUpdateBodyNameRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const warehouseTablesChecksPartialUpdateBodyColumnNameMax = 400

export const warehouseTablesChecksPartialUpdateBodyAiModelMax = 128

export const warehouseTablesChecksPartialUpdateBodyConfidenceMin = 0
export const warehouseTablesChecksPartialUpdateBodyConfidenceMax = 1

export const WarehouseTablesChecksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyNameMax)
            .regex(warehouseTablesChecksPartialUpdateBodyNameRegExp)
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyColumnNameMax)
            .optional()
            .describe('Column the check applies to. Omit for table-scoped types like row_count.'),
        check_type: zod
            .enum(['not_null', 'unique', 'accepted_values', 'relationships', 'row_count', 'freshness', 'custom_sql'])
            .describe(
                '\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            )
            .optional()
            .describe(
                'Which assertion to make. Determines the shape of config; see \/check_types\/.\n\n\* `not_null` - not_null\n\* `unique` - unique\n\* `accepted_values` - accepted_values\n\* `relationships` - relationships\n\* `row_count` - row_count\n\* `freshness` - freshness\n\* `custom_sql` - custom_sql'
            ),
        config: zod
            .record(zod.string(), zod.unknown())
            .optional()
            .describe("Type-specific configuration, validated against the check type's JSON schema."),
        severity: zod
            .enum(['error', 'warn'])
            .describe('\* `error` - error\n\* `warn` - warn')
            .optional()
            .describe(
                "'error' failures mark the subject failing and notify; 'warn' failures only surface.\n\n\* `error` - error\n\* `warn` - warn"
            ),
        enabled: zod.boolean().optional().describe('Disabled checks are never run by any trigger.'),
        tags: zod.array(zod.string()).optional().describe('Free-form string labels for grouping and filtering.'),
        created_source: zod
            .enum(['user', 'ai_generated'])
            .describe('\* `user` - user\n\* `ai_generated` - ai_generated')
            .optional()
            .describe(
                "Whether a human ('user') or an agent ('ai_generated') authored this check.\n\n\* `user` - user\n\* `ai_generated` - ai_generated"
            ),
        ai_model: zod
            .string()
            .max(warehouseTablesChecksPartialUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(warehouseTablesChecksPartialUpdateBodyConfidenceMin)
            .max(warehouseTablesChecksPartialUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe('The subject is implied by the URL (the parent saved query or table), never part of the body.')
