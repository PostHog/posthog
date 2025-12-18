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
 * * `events` - Events
 * `persons` - Persons
 * `sessions` - Sessions
 */
export type ModelEnumApi = (typeof ModelEnumApi)[keyof typeof ModelEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const ModelEnumApi = {
    events: 'events',
    persons: 'persons',
    sessions: 'sessions',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const NullEnumApi = {} as const

/**
 * * `hour` - hour
 * `day` - day
 * `week` - week
 * `every 5 minutes` - every 5 minutes
 */
export type IntervalEnumApi = (typeof IntervalEnumApi)[keyof typeof IntervalEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const IntervalEnumApi = {
    hour: 'hour',
    day: 'day',
    week: 'week',
    every_5_minutes: 'every 5 minutes',
} as const

/**
 * * `Cancelled` - Cancelled
 * `Completed` - Completed
 * `ContinuedAsNew` - Continued As New
 * `Failed` - Failed
 * `FailedRetryable` - Failed Retryable
 * `FailedBilling` - Failed Billing
 * `Terminated` - Terminated
 * `TimedOut` - Timedout
 * `Running` - Running
 * `Starting` - Starting
 */
export type BatchExportRunStatusEnumApi = (typeof BatchExportRunStatusEnumApi)[keyof typeof BatchExportRunStatusEnumApi]

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BatchExportRunStatusEnumApi = {
    Cancelled: 'Cancelled',
    Completed: 'Completed',
    ContinuedAsNew: 'ContinuedAsNew',
    Failed: 'Failed',
    FailedRetryable: 'FailedRetryable',
    FailedBilling: 'FailedBilling',
    Terminated: 'Terminated',
    TimedOut: 'TimedOut',
    Running: 'Running',
    Starting: 'Starting',
} as const

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BatchExportDestinationTypeEnumApi = {
    S3: 'S3',
    Snowflake: 'Snowflake',
    Postgres: 'Postgres',
    Redshift: 'Redshift',
    BigQuery: 'BigQuery',
    Databricks: 'Databricks',
    HTTP: 'HTTP',
    NoOp: 'NoOp',
} as const

/**
 * * `S3` - S3
 * `Snowflake` - Snowflake
 * `Postgres` - Postgres
 * `Redshift` - Redshift
 * `BigQuery` - Bigquery
 * `Databricks` - Databricks
 * `HTTP` - Http
 * `NoOp` - Noop
 */
export type BatchExportDestinationTypeEnumApi =
    (typeof BatchExportDestinationTypeEnumApi)[keyof typeof BatchExportDestinationTypeEnumApi]

export interface PaginatedBatchExportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchExportApi[]
}

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const BatchExportApiModel = { ...ModelEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions
 * @nullable
 */
export type BatchExportApiModel = (typeof BatchExportApiModel)[keyof typeof BatchExportApiModel] | null

/**
 * A schema of custom fields to select when exporting data.
 * @nullable
 */
export type BatchExportApiSchema = unknown | null

/**
 * @nullable
 */
export type BatchExportApiFilters = unknown | null

/**
 * Serializer for a BatchExport model.
 */
export interface BatchExportApi {
    readonly id: string
    /** The team this belongs to. */
    readonly team_id: number
    /** A human-readable name for this BatchExport. */
    name: string
    /**
   * Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions
   * @nullable
   */
    model?: BatchExportApiModel
    destination: BatchExportDestinationApi
    interval: IntervalEnumApi
    /** Whether this BatchExport is paused or not. */
    paused?: boolean
    /** The timestamp at which this BatchExport was created. */
    readonly created_at: string
    /** The timestamp at which this BatchExport was last updated. */
    readonly last_updated_at: string
    /**
     * The timestamp at which this BatchExport was last paused.
     * @nullable
     */
    last_paused_at?: string | null
    /**
     * Time before which any Batch Export runs won't be triggered.
     * @nullable
     */
    start_at?: string | null
    /**
     * Time after which any Batch Export runs won't be triggered.
     * @nullable
     */
    end_at?: string | null
    readonly latest_runs: readonly BatchExportRunApi[]
    hogql_query?: string
    /**
     * A schema of custom fields to select when exporting data.
     * @nullable
     */
    readonly schema: BatchExportApiSchema
    /** @nullable */
    filters?: BatchExportApiFilters
}

export interface PaginatedBatchExportRunListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchExportRunApi[]
}

/**
 * Serializer for a BatchExportRun model.
 */
export interface BatchExportRunApi {
    readonly id: string
    /** The status of this run.

* `Cancelled` - Cancelled
* `Completed` - Completed
* `ContinuedAsNew` - Continued As New
* `Failed` - Failed
* `FailedRetryable` - Failed Retryable
* `FailedBilling` - Failed Billing
* `Terminated` - Terminated
* `TimedOut` - Timedout
* `Running` - Running
* `Starting` - Starting */
    status: BatchExportRunStatusEnumApi
    /**
     * The number of records that have been exported.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    records_completed?: number | null
    /**
     * The latest error that occurred during this run.
     * @nullable
     */
    latest_error?: string | null
    /**
     * The start of the data interval.
     * @nullable
     */
    data_interval_start?: string | null
    /** The end of the data interval. */
    data_interval_end: string
    /**
     * An opaque cursor that may be used to resume.
     * @nullable
     */
    cursor?: string | null
    /** The timestamp at which this BatchExportRun was created. */
    readonly created_at: string
    /**
     * The timestamp at which this BatchExportRun finished, successfully or not.
     * @nullable
     */
    finished_at?: string | null
    /** The timestamp at which this BatchExportRun was last updated. */
    readonly last_updated_at: string
    /**
     * The total count of records that should be exported in this BatchExportRun.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    records_total_count?: number | null
    /**
     * The number of bytes that have been exported in this BatchExportRun.
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     * @nullable
     */
    bytes_exported?: number | null
    /** The BatchExport this run belongs to. */
    readonly batch_export: string
    /**
     * The backfill this run belongs to.
     * @nullable
     */
    backfill?: string | null
}

// eslint-disable-next-line @typescript-eslint/no-redeclare
export const PatchedBatchExportApiModel = { ...ModelEnumApi, ...BlankEnumApi, ...NullEnumApi } as const
/**
 * Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions
 * @nullable
 */
export type PatchedBatchExportApiModel =
    | (typeof PatchedBatchExportApiModel)[keyof typeof PatchedBatchExportApiModel]
    | null

/**
 * A schema of custom fields to select when exporting data.
 * @nullable
 */
export type PatchedBatchExportApiSchema = unknown | null

/**
 * @nullable
 */
export type PatchedBatchExportApiFilters = unknown | null

/**
 * Serializer for a BatchExport model.
 */
export interface PatchedBatchExportApi {
    readonly id?: string
    /** The team this belongs to. */
    readonly team_id?: number
    /** A human-readable name for this BatchExport. */
    name?: string
    /**
   * Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions
   * @nullable
   */
    model?: PatchedBatchExportApiModel
    destination?: BatchExportDestinationApi
    interval?: IntervalEnumApi
    /** Whether this BatchExport is paused or not. */
    paused?: boolean
    /** The timestamp at which this BatchExport was created. */
    readonly created_at?: string
    /** The timestamp at which this BatchExport was last updated. */
    readonly last_updated_at?: string
    /**
     * The timestamp at which this BatchExport was last paused.
     * @nullable
     */
    last_paused_at?: string | null
    /**
     * Time before which any Batch Export runs won't be triggered.
     * @nullable
     */
    start_at?: string | null
    /**
     * Time after which any Batch Export runs won't be triggered.
     * @nullable
     */
    end_at?: string | null
    readonly latest_runs?: readonly BatchExportRunApi[]
    hogql_query?: string
    /**
     * A schema of custom fields to select when exporting data.
     * @nullable
     */
    readonly schema?: PatchedBatchExportApiSchema
    /** @nullable */
    filters?: PatchedBatchExportApiFilters
}

/**
 * Serializer for an BatchExportDestination model.
 */
export interface BatchExportDestinationApi {
    /** A choice of supported BatchExportDestination types.

* `S3` - S3
* `Snowflake` - Snowflake
* `Postgres` - Postgres
* `Redshift` - Redshift
* `BigQuery` - Bigquery
* `Databricks` - Databricks
* `HTTP` - Http
* `NoOp` - Noop */
    type: BatchExportDestinationTypeEnumApi
    /** A JSON field to store all configuration parameters required to access a BatchExportDestination. */
    config?: unknown
    /**
     * The integration for this destination.
     * @nullable
     */
    integration?: number | null
    /** @nullable */
    integration_id?: number | null
}

export type EnvironmentsBatchExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EnvironmentsBatchExportsRunsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}

export type BatchExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BatchExportsList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BatchExportsRunsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}
