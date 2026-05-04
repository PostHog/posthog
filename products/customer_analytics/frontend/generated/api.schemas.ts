/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
    content?: unknown | null
    sidebar?: unknown | null
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
