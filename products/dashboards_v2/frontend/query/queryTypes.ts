import type { AppliedFilter } from '../filters/filtersContext'
import { type TimeRange } from '../filters/time/timeRangeSchema'
import { type PanelQuery } from './querySchema'

/** A query's result in one shape every panel reads, so a chart can switch kind without running its query again. */
export type DataFrame = {
    name?: string
    refId?: string
    /** Tells apart frames that share a name, such as one series per breakdown value. */
    labels?: Record<string, string>
    meta?: FrameMeta
    /** Changes only when the frame's content changes, so a refresh that returns the same data can keep its chart. */
    hash?: string
    fields: {
        name: string
        type: 'time' | 'number' | 'string' | 'boolean' | 'other'
        values: unknown[]
        unit?: string
        labels?: Record<string, string>
    }[]
}

export type FrameMeta = {
    interval?: string | null
    end?: number | null
    truncated?: boolean
    previous?: boolean
}

/** What a panel asks the host's runner to run. The time range is the panel's own, or the one around it. */
export type QueryRequest = {
    query: PanelQuery
    /** The id of the project the query reads. Left out, it reads the project the host's runner was made for. */
    project?: number
    /** Left out, the query runs on the range saved in it. */
    time?: TimeRange
    legend?: string
    /** The filters around the chart that have a value. Left out when none do. The runner applies the kinds it knows. */
    filters?: AppliedFilter[]
}

/** A query's frames, and how fresh they are when the host's runner knows it, such as from a cached result. */
export type QueryResult = {
    frames: DataFrame[]
    /** When the result was computed, as an ISO timestamp. */
    fetchedAt?: string
    /** True when the result is older than its query's refresh interval, so a newer one may be on its way. */
    stale?: boolean
}

/**
 * Runs a panel's query and returns its result. The host supplies it, so the dashboard never fetches data itself.
 * Once `signal` aborts, nothing waits for the result, so the runner can drop the query and reject with an `AbortError`.
 */
export type RunQuery = (request: QueryRequest, signal?: AbortSignal) => Promise<QueryResult>
