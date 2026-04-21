/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface HogFunctionMappingTemplateApi {
    /** Name of this mapping template. */
    name: string
    /**
     * Whether this mapping is enabled by default.
     * @nullable
     */
    include_by_default?: boolean | null
    /**
     * Whether this mapping should match all events by default, hiding the event filter UI.
     * @nullable
     */
    use_all_events_by_default?: boolean | null
    /** Event filters specific to this mapping. */
    filters?: unknown | null
    /** Input values specific to this mapping. */
    inputs?: unknown | null
    /** Additional input schema fields specific to this mapping. */
    inputs_schema?: unknown | null
}

export interface HogFunctionTemplateApi {
    /** Unique template identifier (e.g. 'template-slack'). */
    id: string
    /**
     * Display name of the template.
     * @maxLength 400
     */
    name: string
    /**
     * What this template does.
     * @nullable
     */
    description?: string | null
    /** Source code of the template. */
    code: string
    /**
     * Programming language: 'hog' or 'javascript'.
     * @maxLength 20
     */
    code_language?: string
    /** Schema defining configurable inputs for functions created from this template. */
    inputs_schema: unknown
    /**
     * Function type this template creates.
     * @maxLength 50
     */
    type: string
    /**
     * Lifecycle status: alpha, beta, stable, deprecated, or hidden.
     * @maxLength 20
     */
    status?: string
    /** Category tags for organizing templates. */
    category?: unknown
    /** Whether available on free plans. */
    free?: boolean
    /**
     * URL for the template's icon.
     * @nullable
     */
    icon_url?: string | null
    /** Default event filters. */
    filters?: unknown | null
    /** Default PII masking configuration. */
    masking?: unknown | null
    /**
     * Pre-defined mapping configurations for destination templates.
     * @nullable
     */
    mapping_templates?: HogFunctionMappingTemplateApi[] | null
}

export interface PaginatedHogFunctionTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HogFunctionTemplateApi[]
}

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

/**
 * * `0` - 0
 * `1` - 1
 * `2` - 2
 * `3` - 3
 * `11` - 11
 * `12` - 12
 */
export type HogFunctionStatusStateEnumApi =
    (typeof HogFunctionStatusStateEnumApi)[keyof typeof HogFunctionStatusStateEnumApi]

export const HogFunctionStatusStateEnumApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number11: 11,
    Number12: 12,
} as const

export interface HogFunctionStatusApi {
    state: HogFunctionStatusStateEnumApi
    tokens: number
}

export interface HogFunctionMinimalApi {
    readonly id: string
    /** @nullable */
    readonly type: string | null
    /** @nullable */
    readonly name: string | null
    readonly description: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly enabled: boolean
    readonly hog: string
    readonly filters: unknown | null
    /** @nullable */
    readonly icon_url: string | null
    readonly template: HogFunctionTemplateApi
    readonly status: HogFunctionStatusApi | null
    /** @nullable */
    readonly execution_order: number | null
}

export interface PaginatedHogFunctionMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HogFunctionMinimalApi[]
}

/**
 * * `hog` - hog
 * `liquid` - liquid
 */
export type Templating186EnumApi = (typeof Templating186EnumApi)[keyof typeof Templating186EnumApi]

export const Templating186EnumApi = {
    Hog: 'hog',
    Liquid: 'liquid',
} as const

export interface InputsItemApi {
    value?: unknown
    templating?: Templating186EnumApi
    readonly bytecode: readonly unknown[]
    readonly order: number
    readonly transpiled: unknown
}

/**
 * Values for each input defined in inputs_schema.
 */
export type HogFunctionApiInputs = { [key: string]: InputsItemApi }

/**
 * * `destination` - Destination
 * `site_destination` - Site Destination
 * `internal_destination` - Internal Destination
 * `source_webhook` - Source Webhook
 * `warehouse_source_webhook` - Warehouse Source Webhook
 * `site_app` - Site App
 * `transformation` - Transformation
 */
export type HogFunctionTypeEnumApi = (typeof HogFunctionTypeEnumApi)[keyof typeof HogFunctionTypeEnumApi]

export const HogFunctionTypeEnumApi = {
    Destination: 'destination',
    SiteDestination: 'site_destination',
    InternalDestination: 'internal_destination',
    SourceWebhook: 'source_webhook',
    WarehouseSourceWebhook: 'warehouse_source_webhook',
    SiteApp: 'site_app',
    Transformation: 'transformation',
} as const

/**
 * * `string` - string
 * `number` - number
 * `boolean` - boolean
 * `dictionary` - dictionary
 * `choice` - choice
 * `json` - json
 * `integration` - integration
 * `integration_field` - integration_field
 * `email` - email
 * `native_email` - native_email
 * `posthog_assignee` - posthog_assignee
 * `posthog_ticket_tags` - posthog_ticket_tags
 * `posthog_business_hours` - posthog_business_hours
 */
export type InputsSchemaItemTypeEnumApi = (typeof InputsSchemaItemTypeEnumApi)[keyof typeof InputsSchemaItemTypeEnumApi]

export const InputsSchemaItemTypeEnumApi = {
    String: 'string',
    Number: 'number',
    Boolean: 'boolean',
    Dictionary: 'dictionary',
    Choice: 'choice',
    Json: 'json',
    Integration: 'integration',
    IntegrationField: 'integration_field',
    Email: 'email',
    NativeEmail: 'native_email',
    PosthogAssignee: 'posthog_assignee',
    PosthogTicketTags: 'posthog_ticket_tags',
    PosthogBusinessHours: 'posthog_business_hours',
} as const

/**
 * * `True` - True
 * `False` - False
 * `hog` - hog
 * `liquid` - liquid
 */
export type InputsSchemaItemTemplatingEnumApi =
    (typeof InputsSchemaItemTemplatingEnumApi)[keyof typeof InputsSchemaItemTemplatingEnumApi]

export const InputsSchemaItemTemplatingEnumApi = {
    True: true,
    False: false,
    Hog: 'hog',
    Liquid: 'liquid',
} as const

export type InputsSchemaItemApiChoicesItem = { [key: string]: unknown }

export interface InputsSchemaItemApi {
    type: InputsSchemaItemTypeEnumApi
    key: string
    label?: string
    choices?: InputsSchemaItemApiChoicesItem[]
    required?: boolean
    default?: unknown
    secret?: boolean
    hidden?: boolean
    description?: string
    integration?: string
    integration_key?: string
    requires_field?: string
    integration_field?: string
    requiredScopes?: string
    templating?: InputsSchemaItemTemplatingEnumApi
}

/**
 * * `events` - events
 * `person-updates` - person-updates
 * `data-warehouse-table` - data-warehouse-table
 */
export type HogFunctionFiltersSourceEnumApi =
    (typeof HogFunctionFiltersSourceEnumApi)[keyof typeof HogFunctionFiltersSourceEnumApi]

export const HogFunctionFiltersSourceEnumApi = {
    Events: 'events',
    PersonUpdates: 'person-updates',
    DataWarehouseTable: 'data-warehouse-table',
} as const

export type HogFunctionFiltersApiActionsItem = { [key: string]: unknown }

export type HogFunctionFiltersApiEventsItem = { [key: string]: unknown }

export type HogFunctionFiltersApiDataWarehouseItem = { [key: string]: unknown }

export type HogFunctionFiltersApiPropertiesItem = { [key: string]: unknown }

export interface HogFunctionFiltersApi {
    source?: HogFunctionFiltersSourceEnumApi
    actions?: HogFunctionFiltersApiActionsItem[]
    events?: HogFunctionFiltersApiEventsItem[]
    data_warehouse?: HogFunctionFiltersApiDataWarehouseItem[]
    properties?: HogFunctionFiltersApiPropertiesItem[]
    bytecode?: unknown | null
    transpiled?: unknown
    filter_test_accounts?: boolean
    bytecode_error?: string
}

export interface HogFunctionMaskingApi {
    /**
     * Time-to-live in seconds for the masking cache (60–86400).
     * @minimum 60
     * @maximum 86400
     */
    ttl: number
    /**
     * Optional threshold count before masking applies.
     * @nullable
     */
    threshold?: number | null
    /** Hog expression used to compute the masking hash. */
    hash: string
    /** Compiled bytecode for the hash expression. Auto-generated. */
    bytecode?: unknown | null
}

export type MappingsApiInputs = { [key: string]: InputsItemApi }

export interface MappingsApi {
    name?: string
    inputs_schema?: InputsSchemaItemApi[]
    inputs?: MappingsApiInputs
    filters?: HogFunctionFiltersApi
}

export interface HogFunctionApi {
    readonly id: string
    /** Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.

* `destination` - Destination
* `site_destination` - Site Destination
* `internal_destination` - Internal Destination
* `source_webhook` - Source Webhook
* `warehouse_source_webhook` - Warehouse Source Webhook
* `site_app` - Site App
* `transformation` - Transformation */
    type?: HogFunctionTypeEnumApi | NullEnumApi | null
    /**
     * Display name for the function.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Human-readable description of what this function does. */
    description?: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    /** Whether the function is active and processing events. */
    enabled?: boolean
    /** Soft-delete flag. Set to true to archive the function. */
    deleted?: boolean
    /** Source code. Hog language for most types; TypeScript for site_destination and site_app. */
    hog?: string
    readonly bytecode: unknown | null
    /** @nullable */
    readonly transpiled: string | null
    /** Schema defining the configurable input parameters for this function. */
    inputs_schema?: InputsSchemaItemApi[]
    /** Values for each input defined in inputs_schema. */
    inputs?: HogFunctionApiInputs
    /** Event filters that control which events trigger this function. */
    filters?: HogFunctionFiltersApi
    /** PII masking configuration with TTL, threshold, and hash expression. */
    masking?: HogFunctionMaskingApi | null
    /**
     * Event-to-destination field mappings. Only for destination and site_destination types.
     * @nullable
     */
    mappings?: MappingsApi[] | null
    /**
     * URL for the function's icon displayed in the UI.
     * @nullable
     */
    icon_url?: string | null
    readonly template: HogFunctionTemplateApi
    /**
     * ID of the template to create this function from.
     * @maxLength 400
     * @nullable
     */
    template_id?: string | null
    readonly status: HogFunctionStatusApi | null
    /**
     * Execution priority for transformations. Lower values run first.
     * @minimum 0
     * @maximum 32767
     * @nullable
     */
    execution_order?: number | null
    _create_in_folder?: string
    /** @nullable */
    readonly batch_export_id: string | null
}

/**
 * Values for each input defined in inputs_schema.
 */
export type PatchedHogFunctionApiInputs = { [key: string]: InputsItemApi }

export interface PatchedHogFunctionApi {
    readonly id?: string
    /** Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, or transformation.

* `destination` - Destination
* `site_destination` - Site Destination
* `internal_destination` - Internal Destination
* `source_webhook` - Source Webhook
* `warehouse_source_webhook` - Warehouse Source Webhook
* `site_app` - Site App
* `transformation` - Transformation */
    type?: HogFunctionTypeEnumApi | NullEnumApi | null
    /**
     * Display name for the function.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Human-readable description of what this function does. */
    description?: string
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    /** Whether the function is active and processing events. */
    enabled?: boolean
    /** Soft-delete flag. Set to true to archive the function. */
    deleted?: boolean
    /** Source code. Hog language for most types; TypeScript for site_destination and site_app. */
    hog?: string
    readonly bytecode?: unknown | null
    /** @nullable */
    readonly transpiled?: string | null
    /** Schema defining the configurable input parameters for this function. */
    inputs_schema?: InputsSchemaItemApi[]
    /** Values for each input defined in inputs_schema. */
    inputs?: PatchedHogFunctionApiInputs
    /** Event filters that control which events trigger this function. */
    filters?: HogFunctionFiltersApi
    /** PII masking configuration with TTL, threshold, and hash expression. */
    masking?: HogFunctionMaskingApi | null
    /**
     * Event-to-destination field mappings. Only for destination and site_destination types.
     * @nullable
     */
    mappings?: MappingsApi[] | null
    /**
     * URL for the function's icon displayed in the UI.
     * @nullable
     */
    icon_url?: string | null
    readonly template?: HogFunctionTemplateApi
    /**
     * ID of the template to create this function from.
     * @maxLength 400
     * @nullable
     */
    template_id?: string | null
    readonly status?: HogFunctionStatusApi | null
    /**
     * Execution priority for transformations. Lower values run first.
     * @minimum 0
     * @maximum 32767
     * @nullable
     */
    execution_order?: number | null
    _create_in_folder?: string
    /** @nullable */
    readonly batch_export_id?: string | null
}

/**
 * Mock global variables available during test invocation.
 */
export type HogFunctionInvocationApiGlobals = { [key: string]: unknown }

/**
 * Mock ClickHouse event data to test the function with.
 */
export type HogFunctionInvocationApiClickhouseEvent = { [key: string]: unknown }

export interface HogFunctionInvocationApi {
    /** Full function configuration to test. */
    configuration: HogFunctionApi
    /** Mock global variables available during test invocation. */
    globals?: HogFunctionInvocationApiGlobals
    /** Mock ClickHouse event data to test the function with. */
    clickhouse_event?: HogFunctionInvocationApiClickhouseEvent
    /** When true (default), async functions like fetch() are simulated. */
    mock_async_functions?: boolean
    /** Invocation result status. */
    readonly status: string
    /** Execution logs from the test invocation. */
    readonly logs: readonly unknown[]
    /**
     * Optional invocation ID for correlation.
     * @nullable
     */
    invocation_id?: string | null
}

/**
 * Map of hog function UUIDs to their new execution_order values.
 */
export type PatchedHogFunctionRearrangeApiOrders = { [key: string]: number }

export interface PatchedHogFunctionRearrangeApi {
    /** Map of hog function UUIDs to their new execution_order values. */
    orders?: PatchedHogFunctionRearrangeApiOrders
}

export type HogFunctionTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter to a specific template by its template_id. Deprecated templates are excluded from list results; use the retrieve endpoint to look up a template by ID regardless of status.
     */
    template_id?: string
    /**
     * Filter by template type (e.g. destination, email, sms_provider, broadcast). Defaults to destination if neither type nor types is provided.
     */
    type?: string
    /**
     * Comma-separated list of template types to include (e.g. destination,email,sms_provider).
     */
    types?: string
}

export type HogFunctionsListParams = {
    created_at?: string
    created_by?: number
    enabled?: boolean
    id?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
    /**
     * Multiple values may be separated by commas.
     */
    type?: string[]
    updated_at?: string
}

export type PublicHogFunctionTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter to a specific template by its template_id. Deprecated templates are excluded from list results; use the retrieve endpoint to look up a template by ID regardless of status.
     */
    template_id?: string
    /**
     * Filter by template type (e.g. destination, email, sms_provider, broadcast). Defaults to destination if neither type nor types is provided.
     */
    type?: string
    /**
     * Comma-separated list of template types to include (e.g. destination,email,sms_provider).
     */
    types?: string
}
