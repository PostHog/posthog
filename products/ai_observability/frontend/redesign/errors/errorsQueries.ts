import { ListScope, VolumeBuckets, bucketExpr, hogqlRows, volumeSeries } from '../lists/listQuery'
import type { BreakdownRow } from '../shared/components/BreakdownList'

// Error normalization happens at ingestion, see nodejs/src/ingestion/ai/errors/normalize-error.ts.
const ERROR_EXPR = "coalesce(nullIf(toString(properties.$ai_error_normalized), ''), 'Unknown error')"
const ERROR_EVENTS =
    "event IN ('$ai_generation', '$ai_span', '$ai_trace', '$ai_embedding') AND properties.$ai_is_error = 'true'"

export interface ErrorRow {
    error: string
    occurrences: number
    traces: number
    sessions: number
    users: number
    models: string[]
    firstSeen: string
    lastSeen: string
    volume: number[]
}

export interface ErrorExample {
    uuid: string
    timestamp: string
    traceId: string
    name: string | null
    model: string | null
    latency: number | null
    rawError: string | null
}

export interface ErrorDetail {
    summary: ErrorRow | null
    models: BreakdownRow[]
    users: BreakdownRow[]
    examples: ErrorExample[]
}

interface RawErrorRow {
    error: string
    occurrences: number
    traces: number
    sessions: number
    users: number
    models: string[]
    first_seen: string
    last_seen: string
    volume: unknown
}

function summaryQuery(buckets: VolumeBuckets, where: string, limit: number): string {
    return `SELECT
            ${ERROR_EXPR} AS error,
            count() AS occurrences,
            countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id))) AS traces,
            countDistinctIf(properties.$ai_session_id, notEmpty(toString(properties.$ai_session_id))) AS sessions,
            uniq(distinct_id) AS users,
            arrayFilter(model -> notEmpty(model), topK(3)(toString(properties.$ai_model))) AS models,
            min(timestamp) AS first_seen,
            max(timestamp) AS last_seen,
            sumMap([${bucketExpr(buckets)}], [1]) AS volume
        FROM events
        WHERE ${ERROR_EVENTS} AND ${where} AND {filters}
        GROUP BY error
        ORDER BY occurrences DESC
        LIMIT ${limit}`
}

function toRow(raw: RawErrorRow, buckets: VolumeBuckets): ErrorRow {
    return {
        error: raw.error,
        occurrences: raw.occurrences,
        traces: raw.traces,
        sessions: raw.sessions,
        users: raw.users,
        models: raw.models ?? [],
        firstSeen: raw.first_seen,
        lastSeen: raw.last_seen,
        volume: volumeSeries(buckets, raw.volume),
    }
}

export async function loadErrorRows(scope: ListScope, buckets: VolumeBuckets, search: string): Promise<ErrorRow[]> {
    const where = search ? `positionCaseInsensitive(${ERROR_EXPR}, {search}) > 0` : 'true'
    const rows = await hogqlRows<RawErrorRow>(summaryQuery(buckets, where, 100), scope, { search })
    return rows.map((raw) => toRow(raw, buckets))
}

function breakdownQuery(expr: string): string {
    return `SELECT ${expr} AS label, count() AS count
        FROM events
        WHERE ${ERROR_EVENTS} AND ${ERROR_EXPR} = {key} AND {filters}
        GROUP BY label
        HAVING notEmpty(label)
        ORDER BY count DESC
        LIMIT 6`
}

export async function loadErrorDetail(key: string, scope: ListScope, buckets: VolumeBuckets): Promise<ErrorDetail> {
    const values = { key }
    const [summary, models, users, examples] = await Promise.all([
        hogqlRows<RawErrorRow>(summaryQuery(buckets, `${ERROR_EXPR} = {key}`, 1), scope, values),
        hogqlRows<BreakdownRow>(breakdownQuery('toString(properties.$ai_model)'), scope, values),
        hogqlRows<BreakdownRow>(
            breakdownQuery("coalesce(nullIf(toString(person.properties.email), ''), distinct_id)"),
            scope,
            values
        ),
        hogqlRows<ErrorExample>(
            `SELECT
                toString(uuid) AS uuid,
                timestamp,
                toString(properties.$ai_trace_id) AS traceId,
                nullIf(coalesce(toString(properties.$ai_span_name), toString(properties.$ai_trace_name), ''), '') AS name,
                nullIf(toString(properties.$ai_model), '') AS model,
                toFloat(properties.$ai_latency) AS latency,
                nullIf(toString(properties.$ai_error), '') AS rawError
            FROM events
            WHERE ${ERROR_EVENTS} AND ${ERROR_EXPR} = {key} AND notEmpty(traceId) AND {filters}
            ORDER BY timestamp DESC
            LIMIT 10`,
            scope,
            values
        ),
    ])
    return { summary: summary[0] ? toRow(summary[0], buckets) : null, models, users, examples }
}
