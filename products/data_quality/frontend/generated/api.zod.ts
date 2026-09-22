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
 * Create a check on the table, view or metric named by subject_type and subject_uuid, or refine the one already carrying the same fingerprint. Re-creating a semantically identical check returns 200 and the existing row, never a duplicate.
 */
export const dataQualityChecksCreateBodyNameOneMax = 128

export const dataQualityChecksCreateBodyNameOneRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataQualityChecksCreateBodyNameTwoMax = 0

export const dataQualityChecksCreateBodyColumnNameMax = 400

export const dataQualityChecksCreateBodyAiModelMax = 128

export const dataQualityChecksCreateBodyConfidenceMin = 0
export const dataQualityChecksCreateBodyConfidenceMax = 1

export const DataQualityChecksCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .union([
                zod.string().max(dataQualityChecksCreateBodyNameOneMax).regex(dataQualityChecksCreateBodyNameOneRegExp),
                zod.string().max(dataQualityChecksCreateBodyNameTwoMax),
            ])
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        subject_type: zod
            .enum(['table', 'view', 'metric', 'posthog_table'])
            .describe('\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table')
            .describe(
                "Kind of object to check: 'table', 'view', 'metric', or 'posthog_table'.\n\n\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table"
            ),
        subject_uuid: zod.uuid().describe('Id of the table, view, metric, or PostHog table to check.'),
        column_name: zod
            .string()
            .max(dataQualityChecksCreateBodyColumnNameMax)
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
            .max(dataQualityChecksCreateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(dataQualityChecksCreateBodyConfidenceMin)
            .max(dataQualityChecksCreateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe("The create body, where the subject is named for the only time in a check's life.")

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The subject it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const dataQualityChecksUpdateBodyNameOneMax = 128

export const dataQualityChecksUpdateBodyNameOneRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataQualityChecksUpdateBodyNameTwoMax = 0

export const dataQualityChecksUpdateBodyColumnNameMax = 400

export const dataQualityChecksUpdateBodyAiModelMax = 128

export const dataQualityChecksUpdateBodyConfidenceMin = 0
export const dataQualityChecksUpdateBodyConfidenceMax = 1

export const DataQualityChecksUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .union([
                zod.string().max(dataQualityChecksUpdateBodyNameOneMax).regex(dataQualityChecksUpdateBodyNameOneRegExp),
                zod.string().max(dataQualityChecksUpdateBodyNameTwoMax),
            ])
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(dataQualityChecksUpdateBodyColumnNameMax)
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
            .max(dataQualityChecksUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(dataQualityChecksUpdateBodyConfidenceMin)
            .max(dataQualityChecksUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe(
        'A check as it reads back, and everything an edit may change about it.\n\nThe subject is not one of those: it is writable only on ``DataQualityCheckCreate``.'
    )

/**
 * Edit this check in place, including what it asserts (check_type, column_name, config). The subject it audits is fixed, and the check keeps its id, run history, latest status, and latest run time. A definition or name already held by another active check comes back as a field error, with nothing written.
 */
export const dataQualityChecksPartialUpdateBodyNameOneMax = 128

export const dataQualityChecksPartialUpdateBodyNameOneRegExp = new RegExp('^[A-Za-z][A-Za-z0-9_]\*$')
export const dataQualityChecksPartialUpdateBodyNameTwoMax = 0

export const dataQualityChecksPartialUpdateBodyColumnNameMax = 400

export const dataQualityChecksPartialUpdateBodyAiModelMax = 128

export const dataQualityChecksPartialUpdateBodyConfidenceMin = 0
export const dataQualityChecksPartialUpdateBodyConfidenceMax = 1

export const DataQualityChecksPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .union([
                zod
                    .string()
                    .max(dataQualityChecksPartialUpdateBodyNameOneMax)
                    .regex(dataQualityChecksPartialUpdateBodyNameOneRegExp),
                zod.string().max(dataQualityChecksPartialUpdateBodyNameTwoMax),
            ])
            .optional()
            .describe('Optional identifier-safe handle, unique per project. Omit to address the check by id.'),
        description: zod.string().optional().describe('Why this check exists and what a failure means.'),
        column_name: zod
            .string()
            .max(dataQualityChecksPartialUpdateBodyColumnNameMax)
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
            .max(dataQualityChecksPartialUpdateBodyAiModelMax)
            .optional()
            .describe('Model that generated the check, if AI-authored.'),
        confidence: zod
            .number()
            .min(dataQualityChecksPartialUpdateBodyConfidenceMin)
            .max(dataQualityChecksPartialUpdateBodyConfidenceMax)
            .nullish()
            .describe("AI author's confidence in the check, 0-1."),
        reasoning: zod.string().optional().describe("AI author's reasoning, surfaced as review context."),
    })
    .describe(
        'A check as it reads back, and everything an edit may change about it.\n\nThe subject is not one of those: it is writable only on ``DataQualityCheckCreate``.'
    )

/**
 * Change how often this subject's checks run, or stop running them automatically. Name the subject with subject_type and subject_uuid in the body.
 */
export const DataQualityChecksSchedulePartialUpdateBody = /* @__PURE__ */ zod
    .object({
        subject_type: zod
            .enum(['table', 'view', 'metric', 'posthog_table'])
            .describe('\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table')
            .optional()
            .describe(
                "Kind of object: 'table', 'view', 'metric', or 'posthog_table'.\n\n\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table"
            ),
        subject_uuid: zod.uuid().optional().describe('Id of the table, view, metric, or PostHog table.'),
        interval: zod
            .enum(['1hour', '6hour', '12hour', '24hour', '7day'])
            .describe(
                '\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day'
            )
            .optional()
            .describe(
                'How often all enabled checks on the subject run.\n\n\* `1hour` - 1hour\n\* `6hour` - 6hour\n\* `12hour` - 12hour\n\* `24hour` - 24hour\n\* `7day` - 7day'
            ),
        enabled: zod.boolean().optional().describe('Whether checks run automatically on this schedule.'),
    })
    .describe("Which subject's schedule to change, and what to change about it.")

/**
 * Run checks now: the ones named by check_ids, every enabled check on the subject named by subject_type and subject_uuid, or every enabled check in the project when neither is given. Returns the suite run to poll for the report.
 */
export const DataQualityRunsCreateBody = /* @__PURE__ */ zod
    .object({
        check_ids: zod
            .array(zod.uuid())
            .optional()
            .describe('Ids of the checks to run. Omit to run every enabled check in the project.'),
        subject_type: zod
            .enum(['table', 'view', 'metric', 'posthog_table'])
            .describe('\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table')
            .optional()
            .describe(
                'Narrow the run to one subject. Pass subject_uuid with it. Ignored when check_ids is given.\n\n\* `table` - table\n\* `view` - view\n\* `metric` - metric\n\* `posthog_table` - posthog_table'
            ),
        subject_uuid: zod
            .uuid()
            .optional()
            .describe('Id of the subject to run every enabled check on. Pass subject_type with it.'),
    })
    .describe('What to run in a project-wide suite run.')
