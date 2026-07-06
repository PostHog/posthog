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
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * A team-wide account note — an internal notebook linked to a Customer analytics account.
 */
export interface AccountNoteApi {
    /** URL-safe short ID of the notebook. */
    readonly short_id: string
    /**
     * Title of the note.
     * @nullable
     */
    readonly title: string | null
    /** When the note was created. */
    readonly created_at: string
    /** When the note was last modified. */
    readonly last_modified_at: string
    /** UUID of the account this note is linked to. */
    readonly account_id: string
    /** Name of the account this note is linked to. */
    readonly account_name: string
    /** User who created the note, if known. */
    readonly created_by: UserBasicApi | null
}

export interface PaginatedAccountNoteListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AccountNoteApi[]
}

/**
 * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.
 * @nullable
 */
export type AccountApiProperties = {
    /** @nullable */
    csm?: {
        id: number
        email: string
    } | null
    /** @nullable */
    account_executive?: {
        id: number
        email: string
    } | null
    /** @nullable */
    account_owner?: {
        id: number
        email: string
    } | null
    /** @nullable */
    stripe_customer_id?: string | null
    /** @nullable */
    hubspot_deal_id?: string | null
    /** @nullable */
    billing_id?: string | null
    /** @nullable */
    sfdc_id?: string | null
    /** @nullable */
    zendesk_id?: string | null
    /** @nullable */
    slack_channel_id?: string | null
    /** @nullable */
    usage_dashboard_link?: string | null
} | null

/**
 * A Customer Analytics account — a logical grouping used to assign customer-success ownership.
 */
export interface AccountApi {
    readonly id: string
    /**
     * Human-readable name of the account.
     * @maxLength 400
     */
    name: string
    /**
     * Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional.
     * @maxLength 400
     * @nullable
     */
    external_id?: string | null
    /**
     * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.
     * @nullable
     */
    properties?: AccountApiProperties
    /** Tag names attached to the account. Pass a list to replace existing tags. */
    tags?: string[]
    /** Short IDs of the internal notebooks linked to this account, used to persist investigations, call notes, and other free-form context. Empty list if no notebooks have been created for the account. */
    readonly notebooks: readonly string[]
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedAccountListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AccountApi[]
}

/**
 * An account's current value for a custom property (read shape).
 */
export interface CustomPropertyValueApi {
    /** Unique id of this value record. */
    readonly id: string
    /** Account the value belongs to. */
    readonly account_id: string
    /** Custom property definition the value is for. */
    readonly definition_id: string
    /** The stored value, typed per the property's data type. */
    readonly value: string | number | boolean
    /** When this value was set. */
    readonly created_at: string
    /**
     * Id of the user who set this value, if known.
     * @nullable
     */
    readonly created_by_id: number | null
}

export interface CustomPropertyValueWriteApi {
    /** UUID of the custom property definition whose value to set for this account. */
    definition: string
    /** Value to store, matching the definition's type: a number for number/currency/percent, a boolean for boolean, an ISO-8601 string for date/datetime, or text for text properties. */
    value: string | number | boolean
}

export interface AccountNotebookApi {
    readonly id: string
    readonly short_id: string
    /**
     * Human-readable title of the account notebook.
     * @maxLength 256
     * @nullable
     */
    title?: string | null
    /** Notebook content as a ProseMirror JSON document structure. */
    content?: unknown
    /**
     * Plain text representation of the notebook content for search.
     * @nullable
     */
    text_content?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
}

export interface PaginatedAccountNotebookListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AccountNotebookApi[]
}

/**
 * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.
 * @nullable
 */
export type PatchedAccountApiProperties = {
    /** @nullable */
    csm?: {
        id: number
        email: string
    } | null
    /** @nullable */
    account_executive?: {
        id: number
        email: string
    } | null
    /** @nullable */
    account_owner?: {
        id: number
        email: string
    } | null
    /** @nullable */
    stripe_customer_id?: string | null
    /** @nullable */
    hubspot_deal_id?: string | null
    /** @nullable */
    billing_id?: string | null
    /** @nullable */
    sfdc_id?: string | null
    /** @nullable */
    zendesk_id?: string | null
    /** @nullable */
    slack_channel_id?: string | null
    /** @nullable */
    usage_dashboard_link?: string | null
} | null

/**
 * A Customer Analytics account — a logical grouping used to assign customer-success ownership.
 */
export interface PatchedAccountApi {
    readonly id?: string
    /**
     * Human-readable name of the account.
     * @maxLength 400
     */
    name?: string
    /**
     * Identifier linking this account to its source customer — the analytics group key (the customer's organization id), used to match billing and external records. Optional.
     * @maxLength 400
     * @nullable
     */
    external_id?: string | null
    /**
     * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, usage_dashboard_link). Defaults to an empty object. Unknown keys are rejected.
     * @nullable
     */
    properties?: PatchedAccountApiProperties
    /** Tag names attached to the account. Pass a list to replace existing tags. */
    tags?: string[]
    /** Short IDs of the internal notebooks linked to this account, used to persist investigations, call notes, and other free-form context. Empty list if no notebooks have been created for the account. */
    readonly notebooks?: readonly string[]
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: number | null
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `text` - text
 * * `number` - number
 * * `currency` - currency
 * * `percent` - percent
 * * `date` - date
 * * `datetime` - datetime
 * * `boolean` - boolean
 * * `select` - select
 */
export type CustomPropertyDisplayTypeEnumApi =
    (typeof CustomPropertyDisplayTypeEnumApi)[keyof typeof CustomPropertyDisplayTypeEnumApi]

export const CustomPropertyDisplayTypeEnumApi = {
    Text: 'text',
    Number: 'number',
    Currency: 'currency',
    Percent: 'percent',
    Date: 'date',
    Datetime: 'datetime',
    Boolean: 'boolean',
    Select: 'select',
} as const

/**
 * * `preset-1` - preset-1
 * * `preset-2` - preset-2
 * * `preset-3` - preset-3
 * * `preset-4` - preset-4
 * * `preset-5` - preset-5
 * * `preset-6` - preset-6
 * * `preset-7` - preset-7
 * * `preset-8` - preset-8
 * * `preset-9` - preset-9
 * * `preset-10` - preset-10
 */
export type CustomPropertyOptionColorEnumApi =
    (typeof CustomPropertyOptionColorEnumApi)[keyof typeof CustomPropertyOptionColorEnumApi]

export const CustomPropertyOptionColorEnumApi = {
    Preset1: 'preset-1',
    Preset2: 'preset-2',
    Preset3: 'preset-3',
    Preset4: 'preset-4',
    Preset5: 'preset-5',
    Preset6: 'preset-6',
    Preset7: 'preset-7',
    Preset8: 'preset-8',
    Preset9: 'preset-9',
    Preset10: 'preset-10',
} as const

/**
 * An allowed value of a select custom property.
 */
export interface CustomPropertyOptionApi {
    /**
     * Server-assigned stable id of the option. Omit for new options; send it back unchanged when editing so renames and removals can be told apart.
     * @nullable
     */
    id?: string | null
    /**
     * Display label of the option. Stored as the account's value when picked.
     * @maxLength 400
     */
    label: string
    /** Preset color token used to render the option ('preset-1' through 'preset-10').
     *
     * * `preset-1` - preset-1
     * * `preset-2` - preset-2
     * * `preset-3` - preset-3
     * * `preset-4` - preset-4
     * * `preset-5` - preset-5
     * * `preset-6` - preset-6
     * * `preset-7` - preset-7
     * * `preset-8` - preset-8
     * * `preset-9` - preset-9
     * * `preset-10` - preset-10 */
    color: CustomPropertyOptionColorEnumApi
}

/**
 * Binds a materialized data-warehouse view column to a custom property definition; the view's
 * values are synced onto matching accounts on each materialization.
 */
export interface CustomPropertySourceApi {
    readonly id: string
    /** UUID of the custom property definition this source feeds. One source per definition. */
    definition: string
    /** UUID of the data-warehouse saved query (materialized view) to read values from. */
    saved_query: string
    /**
     * Column in the view whose value is written to the property.
     * @maxLength 400
     */
    source_column: string
    /**
     * Column in the view whose value matches an account's external_id.
     * @maxLength 400
     */
    key_column: string
    /** Whether the source syncs. Auto-disabled after repeated failures or a missing view; re-enabling resets the failure count. */
    is_enabled?: boolean
    /** Consecutive failed sync runs; the source auto-disables at the cap. */
    readonly consecutive_failures: number
    /**
     * When the most recent sync run finished.
     * @nullable
     */
    readonly last_synced_at: string | null
    /**
     * Error summary from the last run, or null if it succeeded.
     * @nullable
     */
    readonly last_sync_error: string | null
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
}

/**
 * A place that uses a custom property definition (read-only).
 */
export interface CustomPropertyReferenceApi {
    /** Id of the referring entity (e.g. the workflow id). */
    readonly id: string
    /** Display name of the referring entity. */
    readonly name: string
    /** Status of the referring entity (e.g. workflow status). */
    readonly status: string
    /** Kind of reference. Currently always 'workflow'. */
    readonly type: string
}

/**
 * A team-scoped definition of a custom account property — the attribute side of the model.
 *
 * Holds only the property's shape (name, display type, big-number flag). Per-account values are
 * stored separately, so this serializer never reads or writes account values.
 */
export interface CustomPropertyDefinitionApi {
    readonly id: string
    /**
     * Human-readable name of the custom property. Unique within the team.
     * @maxLength 400
     */
    name: string
    /**
     * Optional description of what the property represents.
     * @nullable
     */
    description?: string | null
    /** How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.
     *
     * * `text` - text
     * * `number` - number
     * * `currency` - currency
     * * `percent` - percent
     * * `date` - date
     * * `datetime` - datetime
     * * `boolean` - boolean
     * * `select` - select */
    display_type: CustomPropertyDisplayTypeEnumApi
    /** Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties. */
    is_big_number?: boolean
    /**
     * For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types.
     * @nullable
     */
    options?: CustomPropertyOptionApi[] | null
    /** The data-warehouse view-sync binding feeding this property, or null when values are set manually. */
    readonly source: CustomPropertySourceApi | null
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
    /** Workflows that use this property, resolved by definition id. */
    readonly references: readonly CustomPropertyReferenceApi[]
}

export interface PaginatedCustomPropertyDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomPropertyDefinitionApi[]
}

/**
 * A team-scoped definition of a custom account property — the attribute side of the model.
 *
 * Holds only the property's shape (name, display type, big-number flag). Per-account values are
 * stored separately, so this serializer never reads or writes account values.
 */
export interface PatchedCustomPropertyDefinitionApi {
    readonly id?: string
    /**
     * Human-readable name of the custom property. Unique within the team.
     * @maxLength 400
     */
    name?: string
    /**
     * Optional description of what the property represents.
     * @nullable
     */
    description?: string | null
    /** How the property is interpreted and rendered: 'text', 'number', 'currency', 'percent', 'date', 'datetime', 'boolean', or 'select'.
     *
     * * `text` - text
     * * `number` - number
     * * `currency` - currency
     * * `percent` - percent
     * * `date` - date
     * * `datetime` - datetime
     * * `boolean` - boolean
     * * `select` - select */
    display_type?: CustomPropertyDisplayTypeEnumApi
    /** Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties. */
    is_big_number?: boolean
    /**
     * For select properties: the allowed options. Required (non-empty) when display_type is 'select'; cleared server-side for other types.
     * @nullable
     */
    options?: CustomPropertyOptionApi[] | null
    /** The data-warehouse view-sync binding feeding this property, or null when values are set manually. */
    readonly source?: CustomPropertySourceApi | null
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: number | null
    /** @nullable */
    readonly updated_at?: string | null
    /** Workflows that use this property, resolved by definition id. */
    readonly references?: readonly CustomPropertyReferenceApi[]
}

export interface PaginatedCustomPropertySourceListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomPropertySourceApi[]
}

/**
 * Writable fields for updating a source. ``definition`` and ``saved_query`` are create-only, so
 * they are intentionally absent — only these reach the facade's update.
 */
export interface CustomPropertySourceUpdateApi {
    /**
     * Column in the view whose value is written to the property.
     * @maxLength 400
     */
    source_column?: string
    /**
     * Column in the view whose value matches an account's external_id.
     * @maxLength 400
     */
    key_column?: string
    /** Whether the source syncs; re-enabling it resets the failure count. */
    is_enabled?: boolean
}

/**
 * Writable fields for updating a source. ``definition`` and ``saved_query`` are create-only, so
 * they are intentionally absent — only these reach the facade's update.
 */
export interface PatchedCustomPropertySourceUpdateApi {
    /**
     * Column in the view whose value is written to the property.
     * @maxLength 400
     */
    source_column?: string
    /**
     * Column in the view whose value matches an account's external_id.
     * @maxLength 400
     */
    key_column?: string
    /** Whether the source syncs; re-enabling it resets the failure count. */
    is_enabled?: boolean
}

export interface CustomerJourneyApi {
    readonly id: string
    insight: number
    /** @maxLength 400 */
    name: string
    /** @nullable */
    description?: string | null
    readonly created_at: string
    /** @nullable */
    readonly created_by: number | null
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCustomerJourneyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomerJourneyApi[]
}

export interface PatchedCustomerJourneyApi {
    readonly id?: string
    insight?: number
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    description?: string | null
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: number | null
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `person` - Person
 * * `group_0` - Group 0
 * * `group_1` - Group 1
 * * `group_2` - Group 2
 * * `group_3` - Group 3
 * * `group_4` - Group 4
 */
export type CustomerProfileConfigScopeEnumApi =
    (typeof CustomerProfileConfigScopeEnumApi)[keyof typeof CustomerProfileConfigScopeEnumApi]

export const CustomerProfileConfigScopeEnumApi = {
    Person: 'person',
    Group0: 'group_0',
    Group1: 'group_1',
    Group2: 'group_2',
    Group3: 'group_3',
    Group4: 'group_4',
} as const

export interface CustomerProfileConfigApi {
    readonly id: string
    scope: CustomerProfileConfigScopeEnumApi
    content?: unknown
    sidebar?: unknown
    readonly created_at: string
    /** @nullable */
    readonly updated_at: string | null
}

export interface PaginatedCustomerProfileConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CustomerProfileConfigApi[]
}

export interface PatchedCustomerProfileConfigApi {
    readonly id?: string
    scope?: CustomerProfileConfigScopeEnumApi
    content?: unknown
    sidebar?: unknown
    readonly created_at?: string
    /** @nullable */
    readonly updated_at?: string | null
}

/**
 * * `numeric` - numeric
 * * `currency` - currency
 */
export type GroupUsageMetricFormatEnumApi =
    (typeof GroupUsageMetricFormatEnumApi)[keyof typeof GroupUsageMetricFormatEnumApi]

export const GroupUsageMetricFormatEnumApi = {
    Numeric: 'numeric',
    Currency: 'currency',
} as const

/**
 * * `number` - number
 * * `sparkline` - sparkline
 */
export type GroupUsageMetricDisplayEnumApi =
    (typeof GroupUsageMetricDisplayEnumApi)[keyof typeof GroupUsageMetricDisplayEnumApi]

export const GroupUsageMetricDisplayEnumApi = {
    Number: 'number',
    Sparkline: 'sparkline',
} as const

/**
 * * `count` - count
 * * `sum` - sum
 */
export type MathEnumApi = (typeof MathEnumApi)[keyof typeof MathEnumApi]

export const MathEnumApi = {
    Count: 'count',
    Sum: 'sum',
} as const

/**
 * Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.
 *
 * **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.
 *
 * **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.
 */
export type GroupUsageMetricApiFilters = { [key: string]: unknown }

export interface GroupUsageMetricApi {
    readonly id: string
    /**
     * Name of the usage metric. Must be unique per group type within the project.
     * @maxLength 255
     */
    name: string
    /** How the metric value is formatted in the UI. One of `numeric` or `currency`.
     *
     * * `numeric` - numeric
     * * `currency` - currency */
    format?: GroupUsageMetricFormatEnumApi
    /** Rolling time window in days used to compute the metric. Defaults to 7. */
    interval?: number
    /** Visual representation in the UI. One of `number` or `sparkline`.
     *
     * * `number` - number
     * * `sparkline` - sparkline */
    display?: GroupUsageMetricDisplayEnumApi
    /** Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.
     *
     * **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.
     *
     * **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported. */
    filters: GroupUsageMetricApiFilters
    /** Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.
     *
     * * `count` - count
     * * `sum` - sum */
    math?: MathEnumApi
    /**
     * Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.
     * @maxLength 255
     * @nullable
     */
    math_property?: string | null
}

export interface PaginatedGroupUsageMetricListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: GroupUsageMetricApi[]
}

/**
 * Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.
 *
 * **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.
 *
 * **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.
 */
export type PatchedGroupUsageMetricApiFilters = { [key: string]: unknown }

export interface PatchedGroupUsageMetricApi {
    readonly id?: string
    /**
     * Name of the usage metric. Must be unique per group type within the project.
     * @maxLength 255
     */
    name?: string
    /** How the metric value is formatted in the UI. One of `numeric` or `currency`.
     *
     * * `numeric` - numeric
     * * `currency` - currency */
    format?: GroupUsageMetricFormatEnumApi
    /** Rolling time window in days used to compute the metric. Defaults to 7. */
    interval?: number
    /** Visual representation in the UI. One of `number` or `sparkline`.
     *
     * * `number` - number
     * * `sparkline` - sparkline */
    display?: GroupUsageMetricDisplayEnumApi
    /** Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.
     *
     * **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.
     *
     * **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported. */
    filters?: PatchedGroupUsageMetricApiFilters
    /** Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.
     *
     * * `count` - count
     * * `sum` - sum */
    math?: MathEnumApi
    /**
     * Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.
     * @maxLength 255
     * @nullable
     */
    math_property?: string | null
}

export type AccountNotesListParams = {
    /**
     * Only return notes linked to this account.
     */
    account_id?: string
    /**
     * Only return notes created by these user IDs (repeat the param per user).
     */
    created_by?: number[]
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Full-text search across note title and content, plus substring match on account name.
     */
    search?: string
}

export type AccountsListParams = {
    /**
     * Filter by account executive. Use 'unassigned' or an integer user id.
     */
    account_executive?: string
    /**
     * Filter by account owner. Use 'unassigned' or an integer user id.
     */
    account_owner?: string
    /**
     * When true, returns only accounts where CSM, account executive, and account owner are all unset.
     */
    all_roles_unassigned?: boolean
    /**
     * Filter by CSM. Use 'unassigned' for accounts with no CSM, or an integer user id.
     */
    csm?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort order. Defaults to '-created_at'.
     */
    ordering?: string
    /**
     * Case-insensitive substring search across account name and external ID.
     */
    search?: string
    /**
     * JSON-encoded array of tag names to filter by, e.g. `["enterprise","priority"]`. Returns accounts that have any of the listed tags. Malformed values (not a JSON-encoded list of strings) return a 400.
     */
    tags?: string
}

export type AccountsNotebooksListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Sort by creation date or author. Defaults to '-created_at'.
     */
    ordering?: string
    /**
     * Full-text search across notebook title and content.
     */
    search?: string
}

export type CustomPropertyDefinitionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CustomPropertySourcesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CustomerJourneysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CustomerProfileConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type GroupsTypesMetricsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
