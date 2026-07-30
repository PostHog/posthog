/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface PrecomputeInvalidateRequestApi {
    /**
     * Only invalidate jobs for this query hash. Omit to invalidate every hash stored for the team.
     * @maxLength 64
     * @nullable
     */
    query_hash?: string | null
}

export interface PrecomputeInvalidateResponseApi {
    /** Number of READY jobs marked stale. */
    updated_count: number
    /**
     * The hash that was invalidated, or null when all hashes were targeted.
     * @nullable
     */
    query_hash: string | null
}

export interface PrecomputeDebugSampleApi {
    /**
     * query_type tag of the insert that built this hash (identifies the query family).
     * @nullable
     */
    query_type: string | null
    /**
     * Trigger tag of the insert: a warmer trigger name, or empty for a user-initiated read.
     * @nullable
     */
    trigger: string | null
    /**
     * Originating query as JSON (from the insert's log_comment) including date range and property filters — shows which dashboard queries this hash serves.
     * @nullable
     */
    query_json: string | null
    /**
     * When the sampled insert for this hash finished.
     * @nullable
     */
    last_insert_at: string | null
}

/**
 * * `pending` - Pending
 * * `ready` - Ready
 * * `stale` - Stale
 * * `failed` - Failed
 */
export type PrecomputeDebugBucketStatusEnumApi =
    (typeof PrecomputeDebugBucketStatusEnumApi)[keyof typeof PrecomputeDebugBucketStatusEnumApi]

export const PrecomputeDebugBucketStatusEnumApi = {
    Pending: 'pending',
    Ready: 'ready',
    Stale: 'stale',
    Failed: 'failed',
} as const

export interface PrecomputeDebugBucketApi {
    /** Start of the bucket's time window (inclusive). */
    time_range_start: string
    /** End of the bucket's time window (exclusive). */
    time_range_end: string
    /** Lifecycle state of this bucket's job.
     *
     * * `pending` - Pending
     * * `ready` - Ready
     * * `stale` - Stale
     * * `failed` - Failed */
    status: PrecomputeDebugBucketStatusEnumApi
    /**
     * When the bucket's data was last computed; null if never computed.
     * @nullable
     */
    computed_at: string | null
    /**
     * When the bucket's data expires in ClickHouse; null if no TTL recorded.
     * @nullable
     */
    expires_at: string | null
    /**
     * Seconds until the bucket expires; negative when already expired, null if no TTL recorded.
     * @nullable
     */
    ttl_seconds_remaining: number | null
}

/**
 * Job count per lifecycle status for this hash.
 */
export type PrecomputeDebugGroupApiStatusCounts = { [key: string]: number }

export interface PrecomputeDebugGroupApi {
    /** SHA-256 of the normalized insert query this group covers. */
    query_hash: string
    /** Number of bucket jobs stored for this hash (within caps). */
    job_count: number
    /** Job count per lifecycle status for this hash. */
    status_counts: PrecomputeDebugGroupApiStatusCounts
    /** Start of the earliest bucket stored for this hash. */
    earliest_start: string
    /** End of the latest bucket stored for this hash. */
    latest_end: string
    /**
     * Most recent computed_at across the hash's buckets.
     * @nullable
     */
    last_computed_at: string | null
    /** Originating-query sample recovered from query_log; null when no recent insert was found. */
    sample: PrecomputeDebugSampleApi | null
    /** Most recent buckets for this hash (capped at 70). */
    buckets: PrecomputeDebugBucketApi[]
}

export interface PrecomputeDebugResponseApi {
    /** When this snapshot was generated. */
    generated_at: string
    /** Expired/failed jobs older than this many days are omitted; unexpired jobs are always shown. */
    job_lookback_days: number
    /** How far back query_log was searched to label hashes with their originating query. */
    query_log_lookback_days: number
    /** Distinct hashes stored for the team within the job lookback. */
    total_hashes: number
    /** Per-hash groups, most recently computed first. */
    groups: PrecomputeDebugGroupApi[]
}

export type PrecomputeDebugStateParams = {
    /**
     * Maximum number of hash groups to return (1–200).
     */
    limit?: number
}
