import { dayjs } from 'lib/dayjs'

import { ListScope, VolumeBuckets, bucketExpr, hogqlRows, volumeSeries } from '../lists/listQuery'
import type { BreakdownRow } from '../shared/components/BreakdownList'

// Tool call extraction happens at ingestion, see nodejs/src/ingestion/ai/tools/extract-tool-calls.ts.
const TOOLS_ARRAY = "splitByChar(',', ifNull(toString(properties.$ai_tools_called), ''))"
const CALLS_TOOL = `has(${TOOLS_ARRAY}, {key})`

export interface ToolRow {
    tool: string
    calls: number
    /** Calls in the period of the same length just before the range. */
    previousCalls: number
    traces: number
    /** Share of all traces with a generation that called this tool, from 0 to 1. */
    traceShare: number | null
    sessions: number
    users: number
    /** Share of the calling generations that called only this tool, from 0 to 1. */
    soloShare: number
    p95LatencySeconds: number | null
    firstSeen: string
    lastSeen: string
    volume: number[]
}

export interface ToolExample {
    uuid: string
    timestamp: string
    traceId: string
    name: string | null
    model: string | null
    latency: number | null
    isError: boolean
    otherTools: string[]
}

export interface ToolDetail {
    summary: ToolRow | null
    alongside: BreakdownRow[]
    models: BreakdownRow[]
    examples: ToolExample[]
}

interface RawToolRow {
    tool: string
    calls: number
    traces: number
    sessions: number
    users: number
    solo: number
    p95: number | null
    first_seen: string
    last_seen: string
    volume: unknown
}

function summaryQuery(buckets: VolumeBuckets, where: string, limit: number): string {
    return `SELECT
            arrayJoin(${TOOLS_ARRAY}) AS tool,
            count() AS calls,
            countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id))) AS traces,
            countDistinctIf(properties.$ai_session_id, notEmpty(toString(properties.$ai_session_id))) AS sessions,
            uniq(distinct_id) AS users,
            countIf(length(${TOOLS_ARRAY}) = 1) AS solo,
            quantile(0.95)(toFloat(properties.$ai_latency)) AS p95,
            min(timestamp) AS first_seen,
            max(timestamp) AS last_seen,
            sumMap([${bucketExpr(buckets)}], [1]) AS volume
        FROM events
        WHERE event = '$ai_generation' AND notEmpty(toString(properties.$ai_tools_called)) AND ${where} AND {filters}
        GROUP BY tool
        HAVING notEmpty(tool)
        ORDER BY calls DESC
        LIMIT ${limit}`
}

/** The period of the same length that ends where the range starts. */
function previousScope(scope: ListScope, buckets: VolumeBuckets): ListScope {
    const start = dayjs.unix(buckets.startEpoch)
    const length = buckets.seconds * buckets.count
    return {
        ...scope,
        dateFrom: start.subtract(length, 'second').toISOString(),
        dateTo: start.toISOString(),
    }
}

async function previousCalls(
    scope: ListScope,
    buckets: VolumeBuckets,
    where: string,
    values: object
): Promise<Map<string, number>> {
    const rows = await hogqlRows<{ tool: string; calls: number }>(
        `SELECT arrayJoin(${TOOLS_ARRAY}) AS tool, count() AS calls
        FROM events
        WHERE event = '$ai_generation' AND notEmpty(toString(properties.$ai_tools_called)) AND ${where} AND {filters}
        GROUP BY tool`,
        previousScope(scope, buckets),
        values as Record<string, unknown>
    )
    return new Map(rows.map((row) => [row.tool, row.calls]))
}

async function totalTraces(scope: ListScope): Promise<number> {
    const [row] = await hogqlRows<{ traces: number }>(
        `SELECT countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id))) AS traces
        FROM events
        WHERE event = '$ai_generation' AND {filters}`,
        scope
    )
    return row?.traces ?? 0
}

function toRow(raw: RawToolRow, buckets: VolumeBuckets, previous: Map<string, number>, allTraces: number): ToolRow {
    return {
        tool: raw.tool,
        calls: raw.calls,
        previousCalls: previous.get(raw.tool) ?? 0,
        traces: raw.traces,
        traceShare: allTraces > 0 ? raw.traces / allTraces : null,
        sessions: raw.sessions,
        users: raw.users,
        soloShare: raw.calls > 0 ? raw.solo / raw.calls : 0,
        p95LatencySeconds: raw.p95 !== null && Number.isFinite(raw.p95) ? raw.p95 : null,
        firstSeen: raw.first_seen,
        lastSeen: raw.last_seen,
        volume: volumeSeries(buckets, raw.volume),
    }
}

export async function loadToolRows(scope: ListScope, buckets: VolumeBuckets, search: string): Promise<ToolRow[]> {
    // The tool name only exists after the arrayJoin, so the search filters the joined rows.
    const where = 'true'
    const values = { search }
    const [rows, previous, allTraces] = await Promise.all([
        hogqlRows<RawToolRow>(summaryQuery(buckets, where, 200), scope, values),
        previousCalls(scope, buckets, where, values),
        totalTraces(scope),
    ])
    const needle = search.toLowerCase()
    return rows
        .filter((raw) => !needle || raw.tool.toLowerCase().includes(needle))
        .map((raw) => toRow(raw, buckets, previous, allTraces))
}

export async function loadToolDetail(key: string, scope: ListScope, buckets: VolumeBuckets): Promise<ToolDetail> {
    const values = { key }
    const [summary, previous, allTraces, alongside, models, examples] = await Promise.all([
        hogqlRows<RawToolRow>(summaryQuery(buckets, CALLS_TOOL, 200), scope, values),
        previousCalls(scope, buckets, CALLS_TOOL, values),
        totalTraces(scope),
        hogqlRows<BreakdownRow>(
            `SELECT arrayJoin(${TOOLS_ARRAY}) AS label, count() AS count
            FROM events
            WHERE event = '$ai_generation' AND ${CALLS_TOOL} AND {filters}
            GROUP BY label
            HAVING notEmpty(label) AND label != {key}
            ORDER BY count DESC
            LIMIT 6`,
            scope,
            values
        ),
        hogqlRows<BreakdownRow>(
            `SELECT toString(properties.$ai_model) AS label, count() AS count
            FROM events
            WHERE event = '$ai_generation' AND ${CALLS_TOOL} AND {filters}
            GROUP BY label
            HAVING notEmpty(label)
            ORDER BY count DESC
            LIMIT 6`,
            scope,
            values
        ),
        hogqlRows<Omit<ToolExample, 'isError'> & { isError: string | boolean }>(
            `SELECT
                toString(uuid) AS uuid,
                timestamp,
                toString(properties.$ai_trace_id) AS traceId,
                nullIf(toString(properties.$ai_span_name), '') AS name,
                nullIf(toString(properties.$ai_model), '') AS model,
                toFloat(properties.$ai_latency) AS latency,
                toString(properties.$ai_is_error) AS isError,
                arrayFilter(tool -> notEmpty(tool) AND tool != {key}, ${TOOLS_ARRAY}) AS otherTools
            FROM events
            WHERE event = '$ai_generation' AND ${CALLS_TOOL} AND notEmpty(traceId) AND {filters}
            ORDER BY timestamp DESC
            LIMIT 10`,
            scope,
            values
        ),
    ])
    const row = summary.find((raw) => raw.tool === key)
    return {
        summary: row ? toRow(row, buckets, previous, allTraces) : null,
        alongside,
        models,
        examples: examples.map((example) => ({ ...example, isError: String(example.isError) === 'true' })),
    }
}
