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
 * * `entity_id` - entity_id
 * `foreign_key` - foreign_key
 * `timestamp` - timestamp
 * `measure` - measure
 * `dimension` - dimension
 * `monetary` - monetary
 * `free_text` - free_text
 * `enum` - enum
 * `uuid` - uuid
 * `unknown` - unknown
 */
export type SemanticTypeEnumApi = (typeof SemanticTypeEnumApi)[keyof typeof SemanticTypeEnumApi]

export const SemanticTypeEnumApi = {
    EntityId: 'entity_id',
    ForeignKey: 'foreign_key',
    Timestamp: 'timestamp',
    Measure: 'measure',
    Dimension: 'dimension',
    Monetary: 'monetary',
    FreeText: 'free_text',
    Enum: 'enum',
    Uuid: 'uuid',
    Unknown: 'unknown',
} as const

/**
 * * `pii` - pii
 * `sensitive` - sensitive
 * `public` - public
 * `unknown` - unknown
 */
export type PiiClassEnumApi = (typeof PiiClassEnumApi)[keyof typeof PiiClassEnumApi]

export const PiiClassEnumApi = {
    Pii: 'pii',
    Sensitive: 'sensitive',
    Public: 'public',
    Unknown: 'unknown',
} as const

/**
 * Body for catalog-columns-create. Identified by (node_id, name).
 */
export interface UpsertColumnInputApi {
    /** ID of the parent CatalogNode (returned by catalog-nodes-create). */
    node_id: string
    /**
     * Column name as it appears in the underlying table. Case-sensitive. Combined with `node_id` to form the upsert key — calling create again with the same (node_id, name) updates in place.
     * @maxLength 400
     */
    name: string
    /** Ordinal position of the column in the source table. Used for display and stable iteration. */
    position?: number
    /**
     * Raw ClickHouse type string (`String`, `Nullable(DateTime64(3))`, `Array(String)`...). Set when the column comes from a ClickHouse-backed table; null for Postgres-only sources.
     * @maxLength 255
     * @nullable
     */
    clickhouse_type?: string | null
    /**
     * HogQL-normalized type — `String`, `Int`, `Float`, `Boolean`, `DateTime`, `Array`, `JSON`. What the agent sees when reading via `system.columns`. Inferred from clickhouse_type when not set explicitly.
     * @maxLength 128
     * @nullable
     */
    hogql_type?: string | null
    /** Whether the column can hold NULL values. Drives null-handling guidance in generated queries. */
    nullable?: boolean
    /**
     * What the column represents in business terms — meaning, units, valid values, gotchas. Example: "Subscription monthly recurring revenue in USD cents. Excludes refunds. Null for one-time charges."
     * @nullable
     */
    synthetic_description?: string | null
    /** Role of the column for query planning. `entity_id` for primary identifiers, `foreign_key` for join targets, `timestamp` for time filtering, `measure` for aggregation, `dimension` for group-by, `monetary` for currency, `free_text` for unstructured prose, `enum` for closed value sets.

  * `entity_id` - entity_id
  * `foreign_key` - foreign_key
  * `timestamp` - timestamp
  * `measure` - measure
  * `dimension` - dimension
  * `monetary` - monetary
  * `free_text` - free_text
  * `enum` - enum
  * `uuid` - uuid
  * `unknown` - unknown */
    semantic_type?: SemanticTypeEnumApi | null
    /** Sensitivity classification. `pii` for personally identifiable (email, name, IP), `sensitive` for business-confidential, `public` for safe-to-export, `unknown` to defer classification.

  * `pii` - pii
  * `sensitive` - sensitive
  * `public` - public
  * `unknown` - unknown */
    pii_class?: PiiClassEnumApi | null
    /**
     * Model that generated the description/typing — same convention as on nodes.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
    /**
     * Agent confidence (0..1) in the description and semantic typing.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

export interface CatalogColumnDTOApi {
    id: string
    name: string
    position: number
    /** @nullable */
    clickhouse_type: string | null
    /** @nullable */
    hogql_type: string | null
    nullable: boolean
    /** @nullable */
    description: string | null
    /** @nullable */
    semantic_type: string | null
    /** @nullable */
    pii_class: string | null
    /** @nullable */
    confidence: number | null
}

/**
 * Body for catalog-columns-partial-update. Every field optional.
 */
export interface PatchedUpdateColumnInputApi {
    /**
     * What the column represents in business terms — meaning, units, valid values, gotchas.
     * @nullable
     */
    synthetic_description?: string | null
    /** Role of the column for query planning. See create endpoint for full semantics.

  * `entity_id` - entity_id
  * `foreign_key` - foreign_key
  * `timestamp` - timestamp
  * `measure` - measure
  * `dimension` - dimension
  * `monetary` - monetary
  * `free_text` - free_text
  * `enum` - enum
  * `uuid` - uuid
  * `unknown` - unknown */
    semantic_type?: SemanticTypeEnumApi | null
    /** Sensitivity classification. `pii`, `sensitive`, `public`, or `unknown`.

  * `pii` - pii
  * `sensitive` - sensitive
  * `public` - public
  * `unknown` - unknown */
    pii_class?: PiiClassEnumApi | null
    /**
     * Agent confidence (0..1) in the description and semantic typing.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface EventPropertyFilterApi {
    key: string
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: 'event'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: 'person'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'element'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface EventMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'event_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'recording'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface LogEntryPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'log_entry'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export interface GroupPropertyFilterApi {
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    group_type_index?: number | null
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'group'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FeaturePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: 'feature'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: 'flag_evaluates_to'
    /** Feature flag dependency */
    type?: 'flag'
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilterApi {
    key: string
    label?: string | null
    type?: 'hogql'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type EmptyPropertyFilterApi = typeof EmptyPropertyFilterApiValue

export interface DataWarehousePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse_person_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface ErrorTrackingIssueFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'error_tracking_issue'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export interface LogPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export interface SpanPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'revenue_analytics'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type BaseMathTypeApi = (typeof BaseMathTypeApi)[keyof typeof BaseMathTypeApi]

export const BaseMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
    WeeklyActive: 'weekly_active',
    MonthlyActive: 'monthly_active',
    UniqueSession: 'unique_session',
    FirstTimeForUser: 'first_time_for_user',
    FirstMatchingEventForUser: 'first_matching_event_for_user',
} as const

export type FunnelMathTypeApi = (typeof FunnelMathTypeApi)[keyof typeof FunnelMathTypeApi]

export const FunnelMathTypeApi = {
    Total: 'total',
    FirstTimeForUser: 'first_time_for_user',
    FirstTimeForUserWithFilters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

export const PropertyMathTypeApi = {
    Avg: 'avg',
    Sum: 'sum',
    Min: 'min',
    Max: 'max',
    Median: 'median',
    P75: 'p75',
    P90: 'p90',
    P95: 'p95',
    P99: 'p99',
} as const

export type CountPerActorMathTypeApi = (typeof CountPerActorMathTypeApi)[keyof typeof CountPerActorMathTypeApi]

export const CountPerActorMathTypeApi = {
    AvgCountPerActor: 'avg_count_per_actor',
    MinCountPerActor: 'min_count_per_actor',
    MaxCountPerActor: 'max_count_per_actor',
    MedianCountPerActor: 'median_count_per_actor',
    P75CountPerActor: 'p75_count_per_actor',
    P90CountPerActor: 'p90_count_per_actor',
    P95CountPerActor: 'p95_count_per_actor',
    P99CountPerActor: 'p99_count_per_actor',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

export const ExperimentMetricMathTypeApi = {
    Total: 'total',
    Sum: 'sum',
    UniqueSession: 'unique_session',
    Min: 'min',
    Max: 'max',
    Avg: 'avg',
    Dau: 'dau',
    UniqueGroup: 'unique_group',
    Hogql: 'hogql',
} as const

export type CalendarHeatmapMathTypeApi = (typeof CalendarHeatmapMathTypeApi)[keyof typeof CalendarHeatmapMathTypeApi]

export const CalendarHeatmapMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

export const CurrencyCodeApi = {
    Aed: 'AED',
    Afn: 'AFN',
    All: 'ALL',
    Amd: 'AMD',
    Ang: 'ANG',
    Aoa: 'AOA',
    Ars: 'ARS',
    Aud: 'AUD',
    Awg: 'AWG',
    Azn: 'AZN',
    Bam: 'BAM',
    Bbd: 'BBD',
    Bdt: 'BDT',
    Bgn: 'BGN',
    Bhd: 'BHD',
    Bif: 'BIF',
    Bmd: 'BMD',
    Bnd: 'BND',
    Bob: 'BOB',
    Brl: 'BRL',
    Bsd: 'BSD',
    Btc: 'BTC',
    Btn: 'BTN',
    Bwp: 'BWP',
    Byn: 'BYN',
    Bzd: 'BZD',
    Cad: 'CAD',
    Cdf: 'CDF',
    Chf: 'CHF',
    Clp: 'CLP',
    Cny: 'CNY',
    Cop: 'COP',
    Crc: 'CRC',
    Cve: 'CVE',
    Czk: 'CZK',
    Djf: 'DJF',
    Dkk: 'DKK',
    Dop: 'DOP',
    Dzd: 'DZD',
    Egp: 'EGP',
    Ern: 'ERN',
    Etb: 'ETB',
    Eur: 'EUR',
    Fjd: 'FJD',
    Gbp: 'GBP',
    Gel: 'GEL',
    Ghs: 'GHS',
    Gip: 'GIP',
    Gmd: 'GMD',
    Gnf: 'GNF',
    Gtq: 'GTQ',
    Gyd: 'GYD',
    Hkd: 'HKD',
    Hnl: 'HNL',
    Hrk: 'HRK',
    Htg: 'HTG',
    Huf: 'HUF',
    Idr: 'IDR',
    Ils: 'ILS',
    Inr: 'INR',
    Iqd: 'IQD',
    Irr: 'IRR',
    Isk: 'ISK',
    Jmd: 'JMD',
    Jod: 'JOD',
    Jpy: 'JPY',
    Kes: 'KES',
    Kgs: 'KGS',
    Khr: 'KHR',
    Kmf: 'KMF',
    Krw: 'KRW',
    Kwd: 'KWD',
    Kyd: 'KYD',
    Kzt: 'KZT',
    Lak: 'LAK',
    Lbp: 'LBP',
    Lkr: 'LKR',
    Lrd: 'LRD',
    Ltl: 'LTL',
    Lvl: 'LVL',
    Lsl: 'LSL',
    Lyd: 'LYD',
    Mad: 'MAD',
    Mdl: 'MDL',
    Mga: 'MGA',
    Mkd: 'MKD',
    Mmk: 'MMK',
    Mnt: 'MNT',
    Mop: 'MOP',
    Mru: 'MRU',
    Mtl: 'MTL',
    Mur: 'MUR',
    Mvr: 'MVR',
    Mwk: 'MWK',
    Mxn: 'MXN',
    Myr: 'MYR',
    Mzn: 'MZN',
    Nad: 'NAD',
    Ngn: 'NGN',
    Nio: 'NIO',
    Nok: 'NOK',
    Npr: 'NPR',
    Nzd: 'NZD',
    Omr: 'OMR',
    Pab: 'PAB',
    Pen: 'PEN',
    Pgk: 'PGK',
    Php: 'PHP',
    Pkr: 'PKR',
    Pln: 'PLN',
    Pyg: 'PYG',
    Qar: 'QAR',
    Ron: 'RON',
    Rsd: 'RSD',
    Rub: 'RUB',
    Rwf: 'RWF',
    Sar: 'SAR',
    Sbd: 'SBD',
    Scr: 'SCR',
    Sdg: 'SDG',
    Sek: 'SEK',
    Sgd: 'SGD',
    Srd: 'SRD',
    Ssp: 'SSP',
    Stn: 'STN',
    Syp: 'SYP',
    Szl: 'SZL',
    Thb: 'THB',
    Tjs: 'TJS',
    Tmt: 'TMT',
    Tnd: 'TND',
    Top: 'TOP',
    Try: 'TRY',
    Ttd: 'TTD',
    Twd: 'TWD',
    Tzs: 'TZS',
    Uah: 'UAH',
    Ugx: 'UGX',
    Usd: 'USD',
    Uyu: 'UYU',
    Uzs: 'UZS',
    Ves: 'VES',
    Vnd: 'VND',
    Vuv: 'VUV',
    Wst: 'WST',
    Xaf: 'XAF',
    Xcd: 'XCD',
    Xof: 'XOF',
    Xpf: 'XPF',
    Yer: 'YER',
    Zar: 'ZAR',
    Zmw: 'ZMW',
} as const

export interface RevenueCurrencyPropertyConfigApi {
    property?: string | null
    static?: CurrencyCodeApi | null
}

export type EventsNodeApiResponse = { [key: string]: unknown } | null

export interface EventsNodeApi {
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: EventsNodeApiResponse
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type DataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export interface DataWarehouseNodeApi {
    custom_name?: string | null
    distinct_id_field: string
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: 'DataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: DataWarehouseNodeApiResponse
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export interface DateRangeApi {
    /** Start of the date range. Accepts ISO 8601 timestamps (e.g., 2024-01-15T00:00:00Z) or relative formats: -7d (7 days ago), -2w (2 weeks ago), -1m (1 month ago),
  -1h (1 hour ago), -1mStart (start of last month), -1yStart (start of last year). */
    date_from?: string | null
    /** End of the date range. Same format as date_from. Omit or null for "now". */
    date_to?: string | null
    /** Whether the date_from and date_to should be used verbatim. Disables rounding to the start and end of period. */
    explicitDate?: boolean | null
}

export interface HogQLFiltersApi {
    dateRange?: DateRangeApi | null
    filterTestAccounts?: boolean | null
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
}

export type BounceRatePageViewModeApi = (typeof BounceRatePageViewModeApi)[keyof typeof BounceRatePageViewModeApi]

export const BounceRatePageViewModeApi = {
    CountPageviews: 'count_pageviews',
    UniqUrls: 'uniq_urls',
    UniqPageScreenAutocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

export const CustomChannelFieldApi = {
    UtmSource: 'utm_source',
    UtmMedium: 'utm_medium',
    UtmCampaign: 'utm_campaign',
    ReferringDomain: 'referring_domain',
    Url: 'url',
    Pathname: 'pathname',
    Hostname: 'hostname',
} as const

export type CustomChannelOperatorApi = (typeof CustomChannelOperatorApi)[keyof typeof CustomChannelOperatorApi]

export const CustomChannelOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

export interface CustomChannelConditionApi {
    id: string
    key: CustomChannelFieldApi
    op: CustomChannelOperatorApi
    value?: string | string[] | null
}

export interface CustomChannelRuleApi {
    channel_type: string
    combiner: FilterLogicalOperatorApi
    id: string
    items: CustomChannelConditionApi[]
}

export interface DataWarehouseEventsModifierApi {
    distinct_id_field: string
    id_field: string
    table_name: string
    timestamp_field: string
}

export type InCohortViaApi = (typeof InCohortViaApi)[keyof typeof InCohortViaApi]

export const InCohortViaApi = {
    Auto: 'auto',
    Leftjoin: 'leftjoin',
    Subquery: 'subquery',
    LeftjoinConjoined: 'leftjoin_conjoined',
} as const

export type InlineCohortCalculationApi = (typeof InlineCohortCalculationApi)[keyof typeof InlineCohortCalculationApi]

export const InlineCohortCalculationApi = {
    Off: 'off',
    Auto: 'auto',
    Always: 'always',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

export const MaterializationModeApi = {
    Auto: 'auto',
    LegacyNullAsString: 'legacy_null_as_string',
    LegacyNullAsNull: 'legacy_null_as_null',
    Disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

export const MaterializedColumnsOptimizationModeApi = {
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

export const PersonsArgMaxVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

export const PersonsJoinModeApi = {
    Inner: 'inner',
    Left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

export const PersonsOnEventsModeApi = {
    Disabled: 'disabled',
    PersonIdNoOverridePropertiesOnEvents: 'person_id_no_override_properties_on_events',
    PersonIdOverridePropertiesOnEvents: 'person_id_override_properties_on_events',
    PersonIdOverridePropertiesJoined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

export const PropertyGroupsModeApi = {
    Enabled: 'enabled',
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

export const SessionTableVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
    V3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

export const SessionsV2JoinModeApi = {
    String: 'string',
    Uuid: 'uuid',
} as const

export interface HogQLQueryModifiersApi {
    bounceRateDurationSeconds?: number | null
    bounceRatePageViewMode?: BounceRatePageViewModeApi | null
    convertToProjectTimezone?: boolean | null
    customChannelTypeRules?: CustomChannelRuleApi[] | null
    dataWarehouseEventsModifiers?: DataWarehouseEventsModifierApi[] | null
    debug?: boolean | null
    /** If these are provided, the query will fail if these skip indexes are not used */
    forceClickhouseDataSkippingIndexes?: string[] | null
    formatCsvAllowDoubleQuotes?: boolean | null
    inCohortVia?: InCohortViaApi | null
    inlineCohortCalculation?: InlineCohortCalculationApi | null
    materializationMode?: MaterializationModeApi | null
    materializedColumnsOptimizationMode?: MaterializedColumnsOptimizationModeApi | null
    optimizeJoinedFilters?: boolean | null
    optimizeProjections?: boolean | null
    personsArgMaxVersion?: PersonsArgMaxVersionApi | null
    personsJoinMode?: PersonsJoinModeApi | null
    personsOnEventsMode?: PersonsOnEventsModeApi | null
    propertyGroupsMode?: PropertyGroupsModeApi | null
    s3TableUseInvalidColumns?: boolean | null
    /** Push a `session_id_v7 IN (SELECT … FROM events WHERE …)` predicate into the raw_sessions subquery to limit aggregation to sessions that participate in the outer events filter. */
    sessionIdPushdown?: boolean | null
    /** Pre-filter raw_sessions aggregation by `session_id_v7 IN (cheap pre-aggregation that only materializes the columns referenced by the outer-WHERE session predicate)`. Useful when the breakdown/SELECT pulls in many session columns (e.g. `$channel_type`) but the filter only references one (e.g. `$entry_current_url`). */
    sessionPropertyPreAggregation?: boolean | null
    sessionTableVersion?: SessionTableVersionApi | null
    sessionsV2JoinMode?: SessionsV2JoinModeApi | null
    timings?: boolean | null
    useMaterializedViews?: boolean | null
    usePreaggregatedIntermediateResults?: boolean | null
    /** Try to automatically convert HogQL queries to use preaggregated tables at the AST level * */
    usePreaggregatedTableTransforms?: boolean | null
    useWebAnalyticsPreAggregatedTables?: boolean | null
}

export interface HogQLNoticeApi {
    end?: number | null
    fix?: string | null
    message: string
    start?: number | null
}

export type QueryIndexUsageApi = (typeof QueryIndexUsageApi)[keyof typeof QueryIndexUsageApi]

export const QueryIndexUsageApi = {
    Undecisive: 'undecisive',
    No: 'no',
    Partial: 'partial',
    Yes: 'yes',
} as const

export interface HogQLMetadataResponseApi {
    ch_table_names?: string[] | null
    errors: HogQLNoticeApi[]
    isUsingIndices?: QueryIndexUsageApi | null
    isValid?: boolean | null
    notices: HogQLNoticeApi[]
    query?: string | null
    table_names?: string[] | null
    warnings: HogQLNoticeApi[]
}

export interface ClickhouseQueryProgressApi {
    active_cpu_time: number
    bytes_read: number
    estimated_rows_total: number
    rows_read: number
    time_elapsed: number
}

export interface QueryStatusApi {
    /** Whether the query is still running. Will be true if the query is complete, even if it errored. Either result or error will be set. */
    complete?: boolean | null
    dashboard_id?: number | null
    /** When did the query execution task finish (whether successfully or not). */
    end_time?: string | null
    /** If the query failed, this will be set to true. More information can be found in the error_message field. */
    error?: boolean | null
    error_message?: string | null
    expiration_time?: string | null
    id: string
    insight_id?: number | null
    labels?: string[] | null
    /** When was the query execution task picked up by a worker. */
    pickup_time?: string | null
    /** ONLY async queries use QueryStatus. */
    query_async?: true
    query_progress?: ClickhouseQueryProgressApi | null
    results?: unknown
    /** When was query execution task enqueued. */
    start_time?: string | null
    task_id?: string | null
    team_id: number
}

export interface ResolvedDateRangeResponseApi {
    date_from: string
    date_to: string
}

export interface QueryTimingApi {
    /** Key. Shortened to 'k' to save on data. */
    k: string
    /** Time in seconds. Shortened to 't' to save on data. */
    t: number
}

export interface HogQLQueryResponseApi {
    /** Executed ClickHouse query */
    clickhouse?: string | null
    /** Returned columns */
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Query explanation output */
    explain?: string[] | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Query metadata output */
    metadata?: HogQLMetadataResponseApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Input query string */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Types of returned columns */
    types?: unknown[] | null
}

export interface QueryLogTagsApi {
    /** Name of the query, preferably unique. For example web_analytics_vitals */
    name?: string | null
    /** Product responsible for this query. Use string, there's no need to churn the Schema when we add a new product * */
    productKey?: string | null
    /** Scene where this query is shown in the UI. Use string, there's no need to churn the Schema when we add a new Scene * */
    scene?: string | null
}

export interface HogQLVariableApi {
    code_name: string
    isNull?: boolean | null
    value?: unknown
    variableId: string
}

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 */
export type HogQLQueryApiValues = { [key: string]: unknown } | null

/**
 * Variables to be substituted into the query
 */
export type HogQLQueryApiVariables = { [key: string]: HogQLVariableApi } | null

export interface HogQLQueryApi {
    /** Optional direct external data source id for running against a specific source */
    connectionId?: string | null
    explain?: boolean | null
    filters?: HogQLFiltersApi | null
    kind?: 'HogQLQuery'
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Client provided name of the query */
    name?: string | null
    query: string
    response?: HogQLQueryResponseApi | null
    /** Run the selected connection query directly without translating it through HogQL first */
    sendRawQuery?: boolean | null
    tags?: QueryLogTagsApi | null
    /** Constant values that can be referenced with the {placeholder} syntax in the query */
    values?: HogQLQueryApiValues
    /** Variables to be substituted into the query */
    variables?: HogQLQueryApiVariables
    /** version of the node, used for schema migrations */
    version?: number | null
}

/**
 * Schema for `CatalogMetric.definition` — same shape as an `Insight.query.series` item.

A metric is computed from exactly one of: an event count (EventsNode), a data-warehouse
aggregate (DataWarehouseNode), or a raw HogQL query (HogQLQuery). All three carry a
`kind` discriminator so consumers can route on shape without parsing the body.
 */
export type MetricDefinitionSchemaApi = EventsNodeApi | DataWarehouseNodeApi | HogQLQueryApi

export interface CatalogNodeDTOApi {
    columns: CatalogColumnDTOApi[]
    id: string
    team_id: number
    kind: string
    name: string
    /** @nullable */
    description: string | null
    /** @nullable */
    semantic_role: string | null
    /** @nullable */
    business_domain: string | null
    tags: string[]
    /** @nullable */
    first_seen_at: string | null
    /** @nullable */
    last_seen_at: string | null
    /** @nullable */
    last_traversed_at: string | null
    /** @nullable */
    confidence: number | null
    status: string
    /** @nullable */
    reviewed_at: string | null
}

export interface CatalogMetricDTOApi {
    definition: MetricDefinitionSchemaApi
    node: CatalogNodeDTOApi
    id: string
    team_id: number
    name: string
    description: string
    created_at: string
    updated_at: string
}

export interface PaginatedCatalogMetricDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CatalogMetricDTOApi[]
}

/**
 * Body for catalog-metrics-create. team_id is taken from the URL, not the body.

Idempotent on (team, name): re-posting with the same name updates description and
definition in place. The bound CatalogNode(kind=metric) is created on first insert
and reused on update — agents can re-propose metrics across traversal runs safely.
 */
export interface UpsertMetricInputApi {
    /**
     * Stable identifier for the metric, unique per team. Use a short snake_case or kebab-case slug that won't change as the metric evolves (e.g. `monthly_recurring_revenue`, `signup_conversion_rate`). The agent looks metrics up by name before upserting, so keep this stable across runs.
     * @maxLength 400
     */
    name: string
    /** Human-readable description of what this metric measures, when to use it, and any caveats — 1-2 sentences. Becomes the primary signal future agents use to decide whether this is the right metric to reference for a question. */
    description?: string
    /** How the metric is computed. Exactly one of `EventsNode` (event count with math and filters), `DataWarehouseNode` (warehouse-table aggregate), or `HogQLQuery` (raw HogQL SQL) — the same shape an `Insight.query.series` item uses, discriminated by the inner `kind` field. Example: `{"kind": "EventsNode", "event": "signup_completed", "math": "dau"}`. */
    definition: MetricDefinitionSchemaApi
    /**
     * Model that proposed the metric — e.g. `claude-opus-4-7`. Stored on the bound CatalogNode for auditing. Leave null when humans author the metric.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
    /**
     * Agent's confidence (0..1) that this metric is correctly defined and worth showing to humans. Surfaces as a draft/confirmed indicator on the bound CatalogNode. Use 1.0 for metrics derived directly from a popular dashboard's saved query; lower values for inferred or aggregated proposals.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

/**
 * Body for catalog-metrics-partial-update. Every field optional; only supplied fields are written.

Status / tags / semantic_role for the metric live on the bound CatalogNode(kind=metric).
Use the metric DTO's `node_id` to PATCH `/catalog/nodes/:node_id/` for those.
 */
export interface PatchedUpdateMetricInputApi {
    /** Human-readable description of what this metric measures, when to use it, and any caveats. Updating clears the old text — pass the full description, not a diff. */
    description?: string
    /** How the metric is computed. Exactly one of `EventsNode`, `DataWarehouseNode`, or `HogQLQuery` — the same shape `Insight.query.series` uses, discriminated by the inner `kind` field. Replaces the existing definition wholesale; supply the complete body. */
    definition?: MetricDefinitionSchemaApi
}

export interface PaginatedCatalogNodeDTOListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CatalogNodeDTOApi[]
}

/**
 * * `warehouse_table` - warehouse_table
 * `saved_query` - saved_query
 * `system_table` - system_table
 * `posthog_table` - posthog_table
 */
export type UpsertNodeInputKindEnumApi = (typeof UpsertNodeInputKindEnumApi)[keyof typeof UpsertNodeInputKindEnumApi]

export const UpsertNodeInputKindEnumApi = {
    WarehouseTable: 'warehouse_table',
    SavedQuery: 'saved_query',
    SystemTable: 'system_table',
    PosthogTable: 'posthog_table',
} as const

/**
 * Body for catalog-nodes-create. team_id is taken from the URL, not the body.
 */
export interface UpsertNodeInputApi {
    /** What kind of catalog entry this is. `warehouse_table` for an imported data warehouse table, `saved_query` for a derived view, `system_table` for a built-in PostHog system table like `events` or `persons`, `posthog_table` for other first-party tables.

  * `warehouse_table` - warehouse_table
  * `saved_query` - saved_query
  * `system_table` - system_table
  * `posthog_table` - posthog_table */
    kind: UpsertNodeInputKindEnumApi
    /**
     * Stable identifier for the node, unique per (team, kind). For warehouse tables this is the imported table name (e.g. `stripe_charges`). For system tables use the canonical name (e.g. `events`). The agent looks nodes up by name before upserting, so keep this stable across runs.
     * @maxLength 400
     */
    name: string
    /**
     * Set when `kind=warehouse_table` to bind this node to the backing `DataWarehouseTable` row. Used for cascade cleanup when the warehouse table is deleted. Leave null for system/posthog tables.
     * @nullable
     */
    warehouse_table_id?: string | null
    /**
     * Set when `kind=saved_query` to bind this node to the backing `DataWarehouseSavedQuery` row. Leave null for non-saved-query kinds.
     * @nullable
     */
    saved_query_id?: string | null
    /**
     * Markdown description of what this table contains, when to use it, caveats, and how it relates to other tables. Written by the agent or human. Becomes the primary signal future agent runs use to pick the right table for a question.
     * @nullable
     */
    synthetic_description?: string | null
    /**
     * Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`, `event_source`, `identity`. Helps the agent reason about join cardinality and aggregation safety.
     * @maxLength 64
     * @nullable
     */
    semantic_role?: string | null
    /**
     * Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`. Used to group related tables in discovery and to scope cross-source queries.
     * @maxLength 64
     * @nullable
     */
    business_domain?: string | null
    /** Free-form tags for filtering and grouping. Lowercase, short. Examples: `pii`, `derived`, `incremental`, `stripe`, `canonical`. */
    tags?: string[]
    /**
     * Identifier of the model that produced this row when generated by an agent — e.g. `claude-opus-4-7`. Leave null when humans author the description. Used for auditing autofill quality over time.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
    /**
     * Agent's confidence (0..1) in the description and semantic tagging it just wrote. Surfaces as a draft/confirmed indicator and lets review workflows prioritize low-confidence rows.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
}

/**
 * * `proposed` - proposed
 * `approved` - approved
 * `official` - official
 * `drift` - drift
 */
export type UpdateNodeInputStatusEnumApi =
    (typeof UpdateNodeInputStatusEnumApi)[keyof typeof UpdateNodeInputStatusEnumApi]

export const UpdateNodeInputStatusEnumApi = {
    Proposed: 'proposed',
    Approved: 'approved',
    Official: 'official',
    Drift: 'drift',
} as const

/**
 * Body for catalog-nodes-partial-update. Every field optional; only supplied fields are written.
 */
export interface PatchedUpdateNodeInputApi {
    /**
     * Rename the node. Must remain unique per (team, kind). Avoid renaming once agents have linked to it.
     * @maxLength 400
     */
    name?: string
    /**
     * Markdown description of what this table contains, when to use it, caveats, and how it relates to other tables. Becomes the primary signal future agent runs use to pick the right table.
     * @nullable
     */
    synthetic_description?: string | null
    /**
     * Short tag for the table's role in the business model — e.g. `fact`, `dimension`, `bridge`.
     * @maxLength 64
     * @nullable
     */
    semantic_role?: string | null
    /**
     * Domain this table belongs to — e.g. `billing`, `crm`, `product_usage`, `support`.
     * @maxLength 64
     * @nullable
     */
    business_domain?: string | null
    /** Free-form lowercase tags. Replaces the existing tag list when supplied. */
    tags?: string[]
    /**
     * Agent confidence (0..1). Humans can override or clear to mark the row as verified.
     * @minimum 0
     * @maximum 1
     * @nullable
     */
    confidence?: number | null
    /** Review state. `proposed` for AI-authored / unreviewed, `approved` once a human has confirmed it, `official` for canonical definitions, `drift` when the agent detects schema or semantic drift.

  * `proposed` - proposed
  * `approved` - approved
  * `official` - official
  * `drift` - drift */
    status?: UpdateNodeInputStatusEnumApi
}

export interface CatalogRelationshipDTOApi {
    id: string
    source_node_id: string
    /** @nullable */
    source_column: string | null
    target_node_id: string
    /** @nullable */
    target_column: string | null
    kind: string
    confidence: number
    reasoning: string
    status: string
    discovered_at: string
    last_seen_at: string
}

/**
 * Bundles nodes and relationships for the graph view. Drives the React Flow scene
so the client can render the whole topology in one fetch.
 */
export interface CatalogGraphDTOApi {
    readonly nodes: readonly CatalogNodeDTOApi[]
    readonly relationships: readonly CatalogRelationshipDTOApi[]
    /** @nullable */
    generated_at?: string | null
}

/**
 * * `foreign_key` - foreign_key
 * `same_entity` - same_entity
 * `lineage` - lineage
 * `declared_join` - declared_join
 * `join_candidate` - join_candidate
 * `depends_on` - depends_on
 */
export type ProposeRelationshipInputKindEnumApi =
    (typeof ProposeRelationshipInputKindEnumApi)[keyof typeof ProposeRelationshipInputKindEnumApi]

export const ProposeRelationshipInputKindEnumApi = {
    ForeignKey: 'foreign_key',
    SameEntity: 'same_entity',
    Lineage: 'lineage',
    DeclaredJoin: 'declared_join',
    JoinCandidate: 'join_candidate',
    DependsOn: 'depends_on',
} as const

/**
 * Body for catalog-relationships-create. Always lands in PROPOSED status until reviewed.
 */
export interface ProposeRelationshipInputApi {
    /** ID of the node the relationship originates from — e.g. the fact table, source side of a join. */
    source_node_id: string
    /** ID of the node the relationship points to. For joins this is the other table; for foreign keys, the referenced table. */
    target_node_id: string
    /** Relationship type. `foreign_key` when the source column references a target PK. `same_entity` when two columns identify the same business object (Stripe.customer_id ≈ Postgres.users.id). `lineage` when the target table is derived from the source (data-flow lineage). `declared_join` for an officially supported join. `join_candidate` for an inferred-but-unconfirmed join. `depends_on` for a logical dependency that isn't data-flow lineage (e.g. a metric built from an event definition or property).

  * `foreign_key` - foreign_key
  * `same_entity` - same_entity
  * `lineage` - lineage
  * `declared_join` - declared_join
  * `join_candidate` - join_candidate
  * `depends_on` - depends_on */
    kind: ProposeRelationshipInputKindEnumApi
    /**
     * Agent's confidence (0..1) that this relationship is correct. Drives the review queue — low-confidence edges surface for human approval before agents trust them for joins.
     * @minimum 0
     * @maximum 1
     */
    confidence: number
    /**
     * Narrows the source side to a specific column. Set for foreign-key and join edges; null for table-level lineage.
     * @nullable
     */
    source_column_id?: string | null
    /**
     * Narrows the target side to a specific column. Same semantics as source_column_id.
     * @nullable
     */
    target_column_id?: string | null
    /** Free-text justification for the proposal — the data points or column-name signals the agent used. Surfaces in the review UI so a human can decide whether to accept or reject. */
    reasoning?: string
    /**
     * ID of the CatalogTraversalRun this relationship was discovered in. Leave null for ad-hoc proposals.
     * @nullable
     */
    discovered_in_run_id?: string | null
    /**
     * Model that proposed the relationship — same convention as on nodes and columns.
     * @maxLength 64
     * @nullable
     */
    generator_model?: string | null
}

/**
 * * `proposed` - proposed
 * `accepted` - accepted
 * `rejected` - rejected
 * `stale` - stale
 */
export type UpdateRelationshipInputStatusEnumApi =
    (typeof UpdateRelationshipInputStatusEnumApi)[keyof typeof UpdateRelationshipInputStatusEnumApi]

export const UpdateRelationshipInputStatusEnumApi = {
    Proposed: 'proposed',
    Accepted: 'accepted',
    Rejected: 'rejected',
    Stale: 'stale',
} as const

/**
 * Body for catalog-relationships-partial-update. Used by reviewers to accept/reject proposals.
 */
export interface PatchedUpdateRelationshipInputApi {
    /** Review state. `proposed` is the initial state, `accepted` once a human confirms the edge, `rejected` to dismiss it, `stale` when the underlying schema has moved on.

  * `proposed` - proposed
  * `accepted` - accepted
  * `rejected` - rejected
  * `stale` - stale */
    status?: UpdateRelationshipInputStatusEnumApi
    /**
     * Reviewer's confidence (0..1) in the edge after manual inspection.
     * @minimum 0
     * @maximum 1
     */
    confidence?: number
    /** Free-text justification, typically extended during human review. */
    reasoning?: string
}

export type CatalogMetricsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CatalogNodesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
