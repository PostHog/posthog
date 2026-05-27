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
 * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.
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
     * Identifier for the account in an external system (e.g. CRM ID). Optional.
     * @maxLength 400
     * @nullable
     */
    external_id?: string | null
    /**
     * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.
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
 * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.
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
     * Identifier for the account in an external system (e.g. CRM ID). Optional.
     * @maxLength 400
     * @nullable
     */
    external_id?: string | null
    /**
     * Typed account properties: assignment fields (csm, account_executive, account_owner) and external system identifiers (stripe_customer_id, hubspot_deal_id, billing_id, sfdc_id, zendesk_id). Defaults to an empty object. Unknown keys are rejected.
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

/**
 * * `person` - Person
 * `group_0` - Group 0
 * `group_1` - Group 1
 * `group_2` - Group 2
 * `group_3` - Group 3
 * `group_4` - Group 4
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

/**
 * * `numeric` - numeric
 * `currency` - currency
 */
export type GroupUsageMetricFormatEnumApi =
    (typeof GroupUsageMetricFormatEnumApi)[keyof typeof GroupUsageMetricFormatEnumApi]

export const GroupUsageMetricFormatEnumApi = {
    Numeric: 'numeric',
    Currency: 'currency',
} as const

/**
 * * `number` - number
 * `sparkline` - sparkline
 */
export type GroupUsageMetricDisplayEnumApi =
    (typeof GroupUsageMetricDisplayEnumApi)[keyof typeof GroupUsageMetricDisplayEnumApi]

export const GroupUsageMetricDisplayEnumApi = {
    Number: 'number',
    Sparkline: 'sparkline',
} as const

/**
 * * `count` - count
 * `sum` - sum
 */
export type MathEnumApi = (typeof MathEnumApi)[keyof typeof MathEnumApi]

export const MathEnumApi = {
    Count: 'count',
    Sum: 'sum',
} as const

/**
 * Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.

**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.

**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.
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

  * `numeric` - numeric
  * `currency` - currency */
    format?: GroupUsageMetricFormatEnumApi
    /** Rolling time window in days used to compute the metric. Defaults to 7. */
    interval?: number
    /** Visual representation in the UI. One of `number` or `sparkline`.

  * `number` - number
  * `sparkline` - sparkline */
    display?: GroupUsageMetricDisplayEnumApi
    /** Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.

  **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.

  **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported. */
    filters: GroupUsageMetricApiFilters
    /** Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.

  * `count` - count
  * `sum` - sum */
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

**Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.

**Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported.
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

  * `numeric` - numeric
  * `currency` - currency */
    format?: GroupUsageMetricFormatEnumApi
    /** Rolling time window in days used to compute the metric. Defaults to 7. */
    interval?: number
    /** Visual representation in the UI. One of `number` or `sparkline`.

  * `number` - number
  * `sparkline` - sparkline */
    display?: GroupUsageMetricDisplayEnumApi
    /** Filter definition for the metric. Two shapes are accepted, discriminated by an optional `source` key.

  **Events** (default, when `source` is missing or `"events"`): HogFunction filter shape — `events: [...]`, optional `actions: [...]`, `properties: [...]`, `filter_test_accounts: bool`.

  **Data warehouse** (`source: "data_warehouse"`): `table_name` (synced DW table), `timestamp_field` (timestamp column or HogQL expression), `key_field` (column whose value matches the entity key). Currently DW metrics only render on group profiles — person profiles are not yet supported. */
    filters?: PatchedGroupUsageMetricApiFilters
    /** Aggregation function. `count` counts matching events; `sum` sums the value of `math_property` on matching events.

  * `count` - count
  * `sum` - sum */
    math?: MathEnumApi
    /**
     * Required when `math` is `sum`; must be empty when `math` is `count`. For events metrics this is an event property name. For data warehouse metrics this is the column name (or HogQL expression) to sum on the DW table.
     * @maxLength 255
     * @nullable
     */
    math_property?: string | null
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
