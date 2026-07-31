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

export const HogFunctionMappingTemplateApi = zod.object({
    name: zod.string().describe('Name of this mapping template.'),
    include_by_default: zod.boolean().nullish().describe('Whether this mapping is enabled by default.'),
    use_all_events_by_default: zod
        .boolean()
        .nullish()
        .describe('Whether this mapping should match all events by default, hiding the event filter UI.'),
    filters: zod.unknown().optional().describe('Event filters specific to this mapping.'),
    inputs: zod.unknown().optional().describe('Input values specific to this mapping.'),
    inputs_schema: zod.unknown().optional().describe('Additional input schema fields specific to this mapping.'),
})

export type HogFunctionMappingTemplateApi = zod.input<typeof HogFunctionMappingTemplateApi>
export type HogFunctionMappingTemplateApiOutput = zod.output<typeof HogFunctionMappingTemplateApi>

export const hogFunctionTemplateApiNameMax = 400

export const hogFunctionTemplateApiCodeLanguageMax = 20

export const hogFunctionTemplateApiTypeMax = 50

export const hogFunctionTemplateApiStatusMax = 20

export const HogFunctionTemplateApi = zod.object({
    id: zod.string().describe("Unique template identifier (e.g. 'template-slack')."),
    name: zod.string().max(hogFunctionTemplateApiNameMax).describe('Display name of the template.'),
    description: zod.string().nullish().describe('What this template does.'),
    code: zod.string().describe('Source code of the template.'),
    code_language: zod
        .string()
        .max(hogFunctionTemplateApiCodeLanguageMax)
        .optional()
        .describe("Programming language: 'hog' or 'javascript'."),
    inputs_schema: zod
        .unknown()
        .describe('Schema defining configurable inputs for functions created from this template.'),
    type: zod.string().max(hogFunctionTemplateApiTypeMax).describe('Function type this template creates.'),
    status: zod
        .string()
        .max(hogFunctionTemplateApiStatusMax)
        .optional()
        .describe('Lifecycle status: alpha, beta, stable, deprecated, or hidden.'),
    category: zod.unknown().optional().describe('Category tags for organizing templates.'),
    free: zod.boolean().optional().describe('Whether available on free plans.'),
    icon_url: zod.string().nullish().describe("URL for the template's icon."),
    filters: zod.unknown().optional().describe('Default event filters.'),
    masking: zod.unknown().optional().describe('Default PII masking configuration.'),
    mapping_templates: zod
        .array(HogFunctionMappingTemplateApi)
        .nullish()
        .describe('Pre-defined mapping configurations for destination templates.'),
})

export type HogFunctionTemplateApi = zod.input<typeof HogFunctionTemplateApi>
export type HogFunctionTemplateApiOutput = zod.output<typeof HogFunctionTemplateApi>

export const PaginatedHogFunctionTemplateListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(HogFunctionTemplateApi),
})

export type PaginatedHogFunctionTemplateListApi = zod.input<typeof PaginatedHogFunctionTemplateListApi>
export type PaginatedHogFunctionTemplateListApiOutput = zod.output<typeof PaginatedHogFunctionTemplateListApi>

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

export const HogFunctionStatusStateEnumApi = zod
    .union([zod.literal(0), zod.literal(1), zod.literal(2), zod.literal(3), zod.literal(11), zod.literal(12)])
    .describe('\* `0` - 0\n\* `1` - 1\n\* `2` - 2\n\* `3` - 3\n\* `11` - 11\n\* `12` - 12')

export type HogFunctionStatusStateEnumApi = zod.input<typeof HogFunctionStatusStateEnumApi>
export type HogFunctionStatusStateEnumApiOutput = zod.output<typeof HogFunctionStatusStateEnumApi>

export const HogFunctionStatusApi = zod.object({
    state: HogFunctionStatusStateEnumApi,
    tokens: zod.number(),
})

export type HogFunctionStatusApi = zod.input<typeof HogFunctionStatusApi>
export type HogFunctionStatusApiOutput = zod.output<typeof HogFunctionStatusApi>

export const SearchMatchTypeEnumApi = zod.enum(['exact', 'similar'])

export type SearchMatchTypeEnumApi = zod.input<typeof SearchMatchTypeEnumApi>
export type SearchMatchTypeEnumApiOutput = zod.output<typeof SearchMatchTypeEnumApi>

export const HogFunctionMinimalApi = zod.object({
    id: zod.uuid(),
    type: zod.string().nullable(),
    name: zod.string().nullable(),
    description: zod.string(),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }),
    enabled: zod.boolean(),
    hog: zod.string(),
    filters: zod.unknown(),
    icon_url: zod.string().nullable(),
    template: HogFunctionTemplateApi,
    status: zod.union([HogFunctionStatusApi, zod.null()]),
    execution_order: zod.number().nullable(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
})

export type HogFunctionMinimalApi = zod.input<typeof HogFunctionMinimalApi>
export type HogFunctionMinimalApiOutput = zod.output<typeof HogFunctionMinimalApi>

export const PaginatedHogFunctionMinimalListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(HogFunctionMinimalApi),
})

export type PaginatedHogFunctionMinimalListApi = zod.input<typeof PaginatedHogFunctionMinimalListApi>
export type PaginatedHogFunctionMinimalListApiOutput = zod.output<typeof PaginatedHogFunctionMinimalListApi>

export const HogFunctionTypeEnumApi = zod
    .enum([
        'destination',
        'site_destination',
        'internal_destination',
        'source_webhook',
        'warehouse_source_webhook',
        'site_app',
        'transformation',
        'transformation_log',
    ])
    .describe(
        '\* `destination` - Destination\n\* `site_destination` - Site Destination\n\* `internal_destination` - Internal Destination\n\* `source_webhook` - Source Webhook\n\* `warehouse_source_webhook` - Warehouse Source Webhook\n\* `site_app` - Site App\n\* `transformation` - Transformation\n\* `transformation_log` - Transformation Log'
    )

export type HogFunctionTypeEnumApi = zod.input<typeof HogFunctionTypeEnumApi>
export type HogFunctionTypeEnumApiOutput = zod.output<typeof HogFunctionTypeEnumApi>

export const InputsSchemaItemTypeEnumApi = zod
    .enum([
        'string',
        'number',
        'boolean',
        'dictionary',
        'choice',
        'json',
        'integration',
        'integration_multi',
        'integration_field',
        'email',
        'native_email',
        'posthog_assignee',
        'posthog_ticket_tags',
        'posthog_business_hours',
        'non_failure_status_codes',
        'customer_analytics_account_properties',
        'customer_analytics_account_relationships',
    ])
    .describe(
        '\* `string` - string\n\* `number` - number\n\* `boolean` - boolean\n\* `dictionary` - dictionary\n\* `choice` - choice\n\* `json` - json\n\* `integration` - integration\n\* `integration_multi` - integration_multi\n\* `integration_field` - integration_field\n\* `email` - email\n\* `native_email` - native_email\n\* `posthog_assignee` - posthog_assignee\n\* `posthog_ticket_tags` - posthog_ticket_tags\n\* `posthog_business_hours` - posthog_business_hours\n\* `non_failure_status_codes` - non_failure_status_codes\n\* `customer_analytics_account_properties` - customer_analytics_account_properties\n\* `customer_analytics_account_relationships` - customer_analytics_account_relationships'
    )

export type InputsSchemaItemTypeEnumApi = zod.input<typeof InputsSchemaItemTypeEnumApi>
export type InputsSchemaItemTypeEnumApiOutput = zod.output<typeof InputsSchemaItemTypeEnumApi>

export const inputsSchemaItemApiRequiredDefault = false
export const inputsSchemaItemApiSecretDefault = false
export const inputsSchemaItemApiHiddenDefault = false

export const InputsSchemaItemApi = zod.object({
    type: InputsSchemaItemTypeEnumApi,
    key: zod.string(),
    label: zod.string().optional(),
    choices: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    searchable: zod.boolean().optional(),
    required: zod.boolean().default(inputsSchemaItemApiRequiredDefault),
    default: zod.unknown().optional(),
    secret: zod.boolean().default(inputsSchemaItemApiSecretDefault),
    hidden: zod.boolean().default(inputsSchemaItemApiHiddenDefault),
    description: zod.string().optional(),
    integration: zod.string().optional(),
    integration_key: zod.string().optional(),
    requires_field: zod.string().optional(),
    integration_field: zod.string().optional(),
    requiredScopes: zod.string().optional(),
    templating: zod.union([zod.boolean(), zod.enum(['hog', 'liquid'])]).optional(),
})

export type InputsSchemaItemApi = zod.input<typeof InputsSchemaItemApi>
export type InputsSchemaItemApiOutput = zod.output<typeof InputsSchemaItemApi>

export const HogFunctionTemplatingEnumApi = zod.enum(['hog', 'liquid']).describe('\* `hog` - hog\n\* `liquid` - liquid')

export type HogFunctionTemplatingEnumApi = zod.input<typeof HogFunctionTemplatingEnumApi>
export type HogFunctionTemplatingEnumApiOutput = zod.output<typeof HogFunctionTemplatingEnumApi>

export const InputsItemApi = zod.object({
    value: zod.unknown().optional(),
    templating: HogFunctionTemplatingEnumApi.optional(),
    bytecode: zod.array(zod.unknown()),
    order: zod.number(),
    transpiled: zod.unknown(),
})

export type InputsItemApi = zod.input<typeof InputsItemApi>
export type InputsItemApiOutput = zod.output<typeof InputsItemApi>

export const HogFunctionFiltersSourceEnumApi = zod
    .enum(['events', 'person-updates', 'data-warehouse-table'])
    .describe(
        '\* `events` - events\n\* `person-updates` - person-updates\n\* `data-warehouse-table` - data-warehouse-table'
    )

export type HogFunctionFiltersSourceEnumApi = zod.input<typeof HogFunctionFiltersSourceEnumApi>
export type HogFunctionFiltersSourceEnumApiOutput = zod.output<typeof HogFunctionFiltersSourceEnumApi>

export const hogFunctionFiltersApiSourceDefault = `events`

export const HogFunctionFiltersApi = zod.object({
    source: HogFunctionFiltersSourceEnumApi.default(hogFunctionFiltersApiSourceDefault),
    actions: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    events: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    data_warehouse: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    properties: zod.array(zod.record(zod.string(), zod.unknown())).optional(),
    bytecode: zod.unknown().optional(),
    transpiled: zod.unknown().optional(),
    filter_test_accounts: zod.boolean().optional(),
    bytecode_error: zod.string().optional(),
})

export type HogFunctionFiltersApi = zod.input<typeof HogFunctionFiltersApi>
export type HogFunctionFiltersApiOutput = zod.output<typeof HogFunctionFiltersApi>

export const hogFunctionMaskingApiTtlMin = 60
export const hogFunctionMaskingApiTtlMax = 86400

export const HogFunctionMaskingApi = zod.object({
    ttl: zod
        .number()
        .min(hogFunctionMaskingApiTtlMin)
        .max(hogFunctionMaskingApiTtlMax)
        .describe('Time-to-live in seconds for the masking cache (60–86400).'),
    threshold: zod.number().nullish().describe('Optional threshold count before masking applies.'),
    hash: zod.string().describe('Hog expression used to compute the masking hash.'),
    bytecode: zod.unknown().optional().describe('Compiled bytecode for the hash expression. Auto-generated.'),
})

export type HogFunctionMaskingApi = zod.input<typeof HogFunctionMaskingApi>
export type HogFunctionMaskingApiOutput = zod.output<typeof HogFunctionMaskingApi>

export const MappingsApi = zod.object({
    name: zod.string().optional(),
    inputs_schema: zod.array(InputsSchemaItemApi).optional(),
    inputs: zod.record(zod.string(), InputsItemApi).optional(),
    filters: HogFunctionFiltersApi.optional(),
})

export type MappingsApi = zod.input<typeof MappingsApi>
export type MappingsApiOutput = zod.output<typeof MappingsApi>

export const hogFunctionApiNameMax = 400

export const hogFunctionApiTemplateIdMax = 400

export const hogFunctionApiExecutionOrderMin = 0
export const hogFunctionApiExecutionOrderMax = 32767

export const HogFunctionApi = zod.object({
    id: zod.uuid(),
    type: zod
        .union([HogFunctionTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, transformation, or transformation_log.\n\n\* `destination` - Destination\n\* `site_destination` - Site Destination\n\* `internal_destination` - Internal Destination\n\* `source_webhook` - Source Webhook\n\* `warehouse_source_webhook` - Warehouse Source Webhook\n\* `site_app` - Site App\n\* `transformation` - Transformation\n\* `transformation_log` - Transformation Log'
        ),
    name: zod.string().max(hogFunctionApiNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({ offset: true }),
    created_by: UserBasicApi,
    updated_at: zod.iso.datetime({ offset: true }),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown(),
    transpiled: zod.string().nullable(),
    inputs_schema: zod
        .array(InputsSchemaItemApi)
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(zod.string(), InputsItemApi)
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: HogFunctionFiltersApi.optional().describe(
        'Event filters that control which events trigger this function.'
    ),
    masking: zod
        .union([HogFunctionMaskingApi, zod.null()])
        .optional()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(MappingsApi)
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: HogFunctionTemplateApi,
    template_id: zod
        .string()
        .max(hogFunctionApiTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod.union([HogFunctionStatusApi, zod.null()]),
    execution_order: zod
        .number()
        .min(hogFunctionApiExecutionOrderMin)
        .max(hogFunctionApiExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullable(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
})

export type HogFunctionApi = zod.input<typeof HogFunctionApi>
export type HogFunctionApiOutput = zod.output<typeof HogFunctionApi>

export const patchedHogFunctionApiNameMax = 400

export const patchedHogFunctionApiTemplateIdMax = 400

export const patchedHogFunctionApiExecutionOrderMin = 0
export const patchedHogFunctionApiExecutionOrderMax = 32767

export const PatchedHogFunctionApi = zod.object({
    id: zod.uuid().optional(),
    type: zod
        .union([HogFunctionTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, transformation, or transformation_log.\n\n\* `destination` - Destination\n\* `site_destination` - Site Destination\n\* `internal_destination` - Internal Destination\n\* `source_webhook` - Source Webhook\n\* `warehouse_source_webhook` - Warehouse Source Webhook\n\* `site_app` - Site App\n\* `transformation` - Transformation\n\* `transformation_log` - Transformation Log'
        ),
    name: zod.string().max(patchedHogFunctionApiNameMax).nullish().describe('Display name for the function.'),
    description: zod.string().optional().describe('Human-readable description of what this function does.'),
    created_at: zod.iso.datetime({ offset: true }).optional(),
    created_by: UserBasicApi.optional(),
    updated_at: zod.iso.datetime({ offset: true }).optional(),
    enabled: zod.boolean().optional().describe('Whether the function is active and processing events.'),
    deleted: zod.boolean().optional().describe('Soft-delete flag. Set to true to archive the function.'),
    hog: zod
        .string()
        .optional()
        .describe('Source code. Hog language for most types; TypeScript for site_destination and site_app.'),
    bytecode: zod.unknown().optional(),
    transpiled: zod.string().nullish(),
    inputs_schema: zod
        .array(InputsSchemaItemApi)
        .optional()
        .describe('Schema defining the configurable input parameters for this function.'),
    inputs: zod
        .record(zod.string(), InputsItemApi)
        .optional()
        .describe('Values for each input defined in inputs_schema.'),
    filters: HogFunctionFiltersApi.optional().describe(
        'Event filters that control which events trigger this function.'
    ),
    masking: zod
        .union([HogFunctionMaskingApi, zod.null()])
        .optional()
        .describe('PII masking configuration with TTL, threshold, and hash expression.'),
    mappings: zod
        .array(MappingsApi)
        .nullish()
        .describe('Event-to-destination field mappings. Only for destination and site_destination types.'),
    icon_url: zod.string().nullish().describe("URL for the function's icon displayed in the UI."),
    template: HogFunctionTemplateApi.optional(),
    template_id: zod
        .string()
        .max(patchedHogFunctionApiTemplateIdMax)
        .nullish()
        .describe('ID of the template to create this function from.'),
    status: zod.union([HogFunctionStatusApi, zod.null()]).optional(),
    execution_order: zod
        .number()
        .min(patchedHogFunctionApiExecutionOrderMin)
        .max(patchedHogFunctionApiExecutionOrderMax)
        .nullish()
        .describe('Execution priority for transformations. Lower values run first.'),
    _create_in_folder: zod.string().optional(),
    batch_export_id: zod.uuid().nullish(),
    search_match_type: zod
        .union([SearchMatchTypeEnumApi, zod.null()])
        .optional()
        .describe(
            'How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match, returned only when no exact match exists). Null when the list is not filtered by `search`.'
        ),
})

export type PatchedHogFunctionApi = zod.input<typeof PatchedHogFunctionApi>
export type PatchedHogFunctionApiOutput = zod.output<typeof PatchedHogFunctionApi>

export const hogFunctionInvocationApiMockAsyncFunctionsDefault = true

export const HogFunctionInvocationApi = zod.object({
    configuration: HogFunctionApi.describe('Full function configuration to test.'),
    globals: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock global variables available during test invocation.'),
    clickhouse_event: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe('Mock ClickHouse event data to test the function with.'),
    mock_async_functions: zod
        .boolean()
        .default(hogFunctionInvocationApiMockAsyncFunctionsDefault)
        .describe('When true (default), async functions like fetch() are simulated.'),
    status: zod.string().describe('Invocation result status.'),
    logs: zod.array(zod.unknown()).describe('Execution logs from the test invocation.'),
    invocation_id: zod.string().nullish().describe('Optional invocation ID for correlation.'),
})

export type HogFunctionInvocationApi = zod.input<typeof HogFunctionInvocationApi>
export type HogFunctionInvocationApiOutput = zod.output<typeof HogFunctionInvocationApi>

export const AppMetricSeriesApi = zod.object({
    name: zod.string(),
    values: zod.array(zod.number()),
})

export type AppMetricSeriesApi = zod.input<typeof AppMetricSeriesApi>
export type AppMetricSeriesApiOutput = zod.output<typeof AppMetricSeriesApi>

export const AppMetricsResponseApi = zod.object({
    labels: zod.array(zod.string()),
    series: zod.array(AppMetricSeriesApi),
})

export type AppMetricsResponseApi = zod.input<typeof AppMetricsResponseApi>
export type AppMetricsResponseApiOutput = zod.output<typeof AppMetricsResponseApi>

export const AppMetricsTotalsResponseApi = zod.object({
    totals: zod.record(zod.string(), zod.number()),
})

export type AppMetricsTotalsResponseApi = zod.input<typeof AppMetricsTotalsResponseApi>
export type AppMetricsTotalsResponseApiOutput = zod.output<typeof AppMetricsTotalsResponseApi>

export const HogInvocationRerunFilterStatusEnumApi = zod
    .enum(['running', 'succeeded', 'failed'])
    .describe('\* `running` - running\n\* `succeeded` - succeeded\n\* `failed` - failed')

export type HogInvocationRerunFilterStatusEnumApi = zod.input<typeof HogInvocationRerunFilterStatusEnumApi>
export type HogInvocationRerunFilterStatusEnumApiOutput = zod.output<typeof HogInvocationRerunFilterStatusEnumApi>

export const hogInvocationRerunFilterApiMaxAttemptsMax = 255

export const hogInvocationRerunFilterApiMaxCountMax = 10000

export const hogInvocationRerunFilterApiInvocationIdsMax = 10000

export const HogInvocationRerunFilterApi = zod
    .object({
        window_start: zod.iso.datetime({ offset: true }).describe('Inclusive lower bound on `scheduled_at` (UTC).'),
        window_end: zod.iso.datetime({ offset: true }).describe('Exclusive upper bound on `scheduled_at` (UTC).'),
        status: zod
            .array(HogInvocationRerunFilterStatusEnumApi)
            .optional()
            .describe("Restrict to invocations whose latest status is one of these. Defaults to ['failed']."),
        error_kind: zod
            .array(zod.string())
            .optional()
            .describe("Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout')."),
        max_attempts: zod
            .number()
            .min(1)
            .max(hogInvocationRerunFilterApiMaxAttemptsMax)
            .optional()
            .describe('Skip invocations that have already been attempted this many times or more.'),
        max_count: zod
            .number()
            .min(1)
            .max(hogInvocationRerunFilterApiMaxCountMax)
            .optional()
            .describe('Maximum number of invocations to rerun in this request. Server-side cap is 10000.'),
        invocation_ids: zod
            .array(zod.string())
            .max(hogInvocationRerunFilterApiInvocationIdsMax)
            .optional()
            .describe(
                'Optional restriction to specific invocation IDs within the window. Capped at 10000 per request. Always combined with `window_start`\/`window_end` so the ClickHouse query can be partition-pruned.'
            ),
    })
    .describe('Filter shape for the rerun endpoint. `window_start`\/`window_end` are required.')

export type HogInvocationRerunFilterApi = zod.input<typeof HogInvocationRerunFilterApi>
export type HogInvocationRerunFilterApiOutput = zod.output<typeof HogInvocationRerunFilterApi>

export const HogInvocationRerunRequestApi = zod
    .object({
        filter: HogInvocationRerunFilterApi.describe(
            'Required. `window_start` \/ `window_end` pin the query to a small set of date partitions on the `hog_invocation_results` table. Optional `invocation_ids` restricts to specific invocations within that window.'
        ),
    })
    .describe('Rerun invocations of a hog function or hog flow from their stored payloads.')

export type HogInvocationRerunRequestApi = zod.input<typeof HogInvocationRerunRequestApi>
export type HogInvocationRerunRequestApiOutput = zod.output<typeof HogInvocationRerunRequestApi>

export const HogInvocationRerunResponseApi = zod
    .object({
        rerun_job_id: zod
            .string()
            .describe('ID of the cyclotron wrapper job that will run the rerun. Use this to poll status.'),
        queued_count: zod.number().describe('Always 0 — rerun runs asynchronously. Kept for response shape stability.'),
        skipped_count: zod
            .number()
            .describe('Always 0 — rerun runs asynchronously. Kept for response shape stability.'),
    })
    .describe(
        'Response from the rerun endpoint. The endpoint only enqueues a wrapper\njob onto the cyclotron `rerun` queue — the actual ClickHouse paging and\nre-enqueue work happens asynchronously in the `cdp-rerun-worker` service.\nUse `rerun_job_id` to look up progress on the wrapper job later.'
    )

export type HogInvocationRerunResponseApi = zod.input<typeof HogInvocationRerunResponseApi>
export type HogInvocationRerunResponseApiOutput = zod.output<typeof HogInvocationRerunResponseApi>

export const PatchedHogFunctionRearrangeApi = zod.object({
    orders: zod
        .record(zod.string(), zod.number())
        .optional()
        .describe('Map of hog function UUIDs to their new execution_order values.'),
})

export type PatchedHogFunctionRearrangeApi = zod.input<typeof PatchedHogFunctionRearrangeApi>
export type PatchedHogFunctionRearrangeApiOutput = zod.output<typeof PatchedHogFunctionRearrangeApi>

export const PluginLogEntrySourceEnumApi = zod
    .enum(['SYSTEM', 'PLUGIN', 'CONSOLE'])
    .describe('\* `SYSTEM` - SYSTEM\n\* `PLUGIN` - PLUGIN\n\* `CONSOLE` - CONSOLE')

export type PluginLogEntrySourceEnumApi = zod.input<typeof PluginLogEntrySourceEnumApi>
export type PluginLogEntrySourceEnumApiOutput = zod.output<typeof PluginLogEntrySourceEnumApi>

export const PluginLogEntryTypeEnumApi = zod
    .enum(['DEBUG', 'LOG', 'INFO', 'WARN', 'ERROR'])
    .describe('\* `DEBUG` - DEBUG\n\* `LOG` - LOG\n\* `INFO` - INFO\n\* `WARN` - WARN\n\* `ERROR` - ERROR')

export type PluginLogEntryTypeEnumApi = zod.input<typeof PluginLogEntryTypeEnumApi>
export type PluginLogEntryTypeEnumApiOutput = zod.output<typeof PluginLogEntryTypeEnumApi>

export const PluginLogEntryApi = zod.object({
    id: zod.uuid(),
    team_id: zod.number(),
    plugin_id: zod.number(),
    plugin_config_id: zod.number(),
    timestamp: zod.iso.datetime({ offset: true }),
    source: PluginLogEntrySourceEnumApi,
    type: PluginLogEntryTypeEnumApi,
    message: zod.string(),
    instance_id: zod.uuid(),
})

export type PluginLogEntryApi = zod.input<typeof PluginLogEntryApi>
export type PluginLogEntryApiOutput = zod.output<typeof PluginLogEntryApi>

export const PaginatedPluginLogEntryListApi = zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(PluginLogEntryApi),
})

export type PaginatedPluginLogEntryListApi = zod.input<typeof PaginatedPluginLogEntryListApi>
export type PaginatedPluginLogEntryListApiOutput = zod.output<typeof PaginatedPluginLogEntryListApi>
