import { ListScope, VolumeBuckets, bucketExpr, hogqlRows, volumeSeries } from '../lists/listQuery'
import type { BreakdownRow } from '../shared/components/BreakdownList'

const PERSON_EMAIL = "nullIf(toString(person.properties.email), '')"
const PERSON_NAME = "nullIf(toString(person.properties.name), '')"
const IS_ERROR = "(properties.$ai_is_error = 'true' OR notEmpty(toString(properties.$ai_error)))"

export interface PersonRow {
    distinctId: string
    email: string | null
    name: string | null
    traces: number
    generations: number
    errors: number
    costUsd: number
    p95LatencySeconds: number | null
    firstSeen: string
    lastSeen: string
    volume: number[]
}

export interface PersonTrace {
    traceId: string
    timestamp: string
    name: string | null
    generations: number
    errors: number
    costUsd: number
    latency: number | null
    models: string[]
}

export interface PersonDetail {
    summary: PersonRow | null
    models: BreakdownRow[]
    tools: BreakdownRow[]
    traces: PersonTrace[]
}

interface RawPersonRow {
    distinct_id: string
    email: string | null
    name: string | null
    traces: number
    generations: number
    errors: number
    cost: number | null
    p95: number | null
    first_seen: string
    last_seen: string
    volume: unknown
}

function summaryQuery(buckets: VolumeBuckets, where: string, limit: number): string {
    return `SELECT
            distinct_id,
            argMax(${PERSON_EMAIL}, timestamp) AS email,
            argMax(${PERSON_NAME}, timestamp) AS name,
            countDistinctIf(properties.$ai_trace_id, notEmpty(toString(properties.$ai_trace_id))) AS traces,
            count() AS generations,
            countIf(${IS_ERROR}) AS errors,
            sum(toFloat(properties.$ai_total_cost_usd)) AS cost,
            quantile(0.95)(toFloat(properties.$ai_latency)) AS p95,
            min(timestamp) AS first_seen,
            max(timestamp) AS last_seen,
            sumMap([${bucketExpr(buckets)}], [1]) AS volume
        FROM events
        WHERE event = '$ai_generation' AND ${where} AND {filters}
        GROUP BY distinct_id
        ORDER BY generations DESC
        LIMIT ${limit}`
}

function toRow(raw: RawPersonRow, buckets: VolumeBuckets): PersonRow {
    return {
        distinctId: raw.distinct_id,
        email: raw.email,
        name: raw.name,
        traces: raw.traces,
        generations: raw.generations,
        errors: raw.errors,
        costUsd: raw.cost ?? 0,
        p95LatencySeconds: raw.p95 !== null && Number.isFinite(raw.p95) ? raw.p95 : null,
        firstSeen: raw.first_seen,
        lastSeen: raw.last_seen,
        volume: volumeSeries(buckets, raw.volume),
    }
}

export async function loadPersonRows(scope: ListScope, buckets: VolumeBuckets, search: string): Promise<PersonRow[]> {
    const where = search
        ? `(positionCaseInsensitive(distinct_id, {search}) > 0 OR positionCaseInsensitive(ifNull(${PERSON_EMAIL}, ''), {search}) > 0)`
        : 'true'
    const rows = await hogqlRows<RawPersonRow>(summaryQuery(buckets, where, 200), scope, { search })
    return rows.map((raw) => toRow(raw, buckets))
}

function breakdownQuery(expr: string): string {
    return `SELECT ${expr} AS label, count() AS count
        FROM events
        WHERE event = '$ai_generation' AND distinct_id = {key} AND {filters}
        GROUP BY label
        HAVING notEmpty(label)
        ORDER BY count DESC
        LIMIT 6`
}

export async function loadPersonDetail(key: string, scope: ListScope, buckets: VolumeBuckets): Promise<PersonDetail> {
    const values = { key }
    const [summary, models, tools, traces] = await Promise.all([
        hogqlRows<RawPersonRow>(summaryQuery(buckets, 'distinct_id = {key}', 1), scope, values),
        hogqlRows<BreakdownRow>(breakdownQuery('toString(properties.$ai_model)'), scope, values),
        hogqlRows<BreakdownRow>(
            breakdownQuery("arrayJoin(splitByChar(',', ifNull(toString(properties.$ai_tools_called), '')))"),
            scope,
            values
        ),
        hogqlRows<Omit<PersonTrace, 'timestamp'> & { started_at: string }>(
            `SELECT
                toString(properties.$ai_trace_id) AS traceId,
                min(timestamp) AS started_at,
                nullIf(argMin(toString(properties.$ai_span_name), timestamp), '') AS name,
                count() AS generations,
                countIf(${IS_ERROR}) AS errors,
                sum(toFloat(properties.$ai_total_cost_usd)) AS costUsd,
                sum(toFloat(properties.$ai_latency)) AS latency,
                arrayFilter(model -> notEmpty(model), groupUniqArray(toString(properties.$ai_model))) AS models
            FROM events
            WHERE event = '$ai_generation' AND distinct_id = {key} AND notEmpty(traceId) AND {filters}
            GROUP BY traceId
            ORDER BY started_at DESC
            LIMIT 15`,
            scope,
            values
        ),
    ])
    return {
        summary: summary[0] ? toRow(summary[0], buckets) : null,
        models,
        tools,
        traces: traces.map(({ started_at, ...trace }) => ({ ...trace, timestamp: started_at })),
    }
}
