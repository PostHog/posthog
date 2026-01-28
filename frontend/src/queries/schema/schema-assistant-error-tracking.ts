/**
 * Schema types for Max AI error tracking tools
 */

/** Preview of an error tracking issue for display in Max AI chat */
export interface MaxErrorTrackingIssuePreview {
    /** Issue ID */
    id: string
    /** Issue name/title */
    name: string | null
    /** Issue description or exception message */
    description: string | null
    /** Issue status (active, resolved, etc.) */
    status: string
    /** Library/runtime that generated the error */
    library: string | null
    /** When the issue was first seen */
    first_seen: string | null
    /** When the issue was last seen */
    last_seen: string | null
    /** Total number of occurrences */
    occurrences: number
    /** Number of affected users */
    users: number
    /** Number of affected sessions */
    sessions: number
}

/** Response from error tracking search tool containing filters, pagination, and results */
export interface MaxErrorTrackingSearchResponse {
    /** Issue status filter (active, resolved, etc.) */
    status?: string | null
    /** Free text search query */
    search_query?: string | null
    /** Start of date range */
    date_from?: string | null
    /** End of date range */
    date_to?: string | null
    /** Field to order by */
    order_by?: string | null
    /** Order direction (ASC or DESC) */
    order_direction?: string | null
    /** Number of results to return */
    limit?: number | null
    /** Whether there are more results available */
    has_more?: boolean | null
    /** Cursor for pagination */
    next_cursor?: string | null
    /** Preview of issues found matching the filters */
    issues?: MaxErrorTrackingIssuePreview[] | null
}
