import { humanFriendlyNumber } from 'lib/utils/numbers'

import { QueryScanResponse, QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { DashboardTile, InsightShortId, QueryBasedInsightModel } from '~/types'

export interface QueryScanState {
    summary: QueryScanSummary
    findings: QueryScanWarning[]
    cacheKey: string | null
    /** The message "Fix with AI" sends, built by the backend. Null when nothing in the query can be fixed. */
    assistantPrompt: string | null
}

export interface QueryScanPollResult {
    cacheKey: string
    scan: QueryScanResponse
}

interface ScanCarrier {
    query_scan?: QueryScanSummary
    cache_key?: string
    warnings?: unknown
}

function asObject(value: unknown): Record<string, unknown> | null {
    return value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null
}

function asCarrier(value: unknown): ScanCarrier | null {
    const object = asObject(value)
    return object && asObject(object.query_scan) ? (object as ScanCarrier) : null
}

// A killed run has no response, so its scan rides on the error: on `extra` for a blocking run and
// on `query_status` for an async one.
function errorScanCarrier(responseErrorObject: unknown): ScanCarrier | null {
    const body = asObject(asObject(responseErrorObject)?.data)
    if (!body) {
        return null
    }
    return asCarrier(body.extra) ?? asCarrier(body.query_status)
}

export function queryScanFindings(warnings: unknown): QueryScanWarning[] {
    if (!Array.isArray(warnings)) {
        return []
    }
    return warnings.filter((warning): warning is QueryScanWarning => asObject(warning)?.type === 'query_scan')
}

// A mode other than `show` keeps every surface silent while the scan only logs.
export function resolveQueryScan(
    response: unknown,
    responseErrorObject: unknown,
    polled: QueryScanPollResult | null
): QueryScanState | null {
    const carrier = asCarrier(response) ?? errorScanCarrier(responseErrorObject)
    const summary = carrier?.query_scan
    if (!summary || summary.mode !== 'show') {
        return null
    }
    const cacheKey = typeof carrier?.cache_key === 'string' ? carrier.cache_key : null
    // A poll outlives the run that started it, so a result for an earlier query would otherwise
    // decorate whatever response is on screen when it lands.
    if (!polled || polled.cacheKey !== cacheKey) {
        return {
            summary,
            findings: queryScanFindings(carrier?.warnings),
            cacheKey,
            assistantPrompt: summary.assistant_prompt ?? null,
        }
    }
    const { scan } = polled
    return {
        summary: {
            ...summary,
            status: scan.status,
            range_share: scan.range_share,
            project_share: scan.project_share,
            // `killed` describes this run; the stored analysis can be of an earlier run that was stopped.
            killed: summary.killed ?? false,
        },
        findings: [...queryScanFindings(carrier?.warnings), ...scan.warnings],
        cacheKey,
        assistantPrompt: scan.assistant_prompt ?? null,
    }
}

function formatRows(rows: integer): string {
    return humanFriendlyNumber(rows)
}

function formatSeconds(durationMs: integer): string {
    return humanFriendlyNumber(durationMs / 1000, 1, 1)
}

export function queryScanStatLine(summary: QueryScanSummary): string {
    const rows = formatRows(summary.rows_read)
    const seconds = formatSeconds(summary.duration_ms)
    if (summary.killed) {
        return `ClickHouse stopped it after ${seconds} s, having read ${rows} rows.`
    }
    if (summary.status === 'done' && typeof summary.range_share === 'number') {
        const percent = Math.round(summary.range_share * 100)
        return `Read ${rows} rows in ${seconds} s, about ${percent}% of the events in this date range.`
    }
    return `Read ${rows} rows in ${seconds} s.`
}

export function queryScanTileStatLine(summary: QueryScanSummary): string {
    const rows = formatRows(summary.rows_read)
    const seconds = formatSeconds(summary.duration_ms)
    if (summary.killed) {
        return `ClickHouse stopped this tile's last run after ${seconds} s, having read ${rows} rows.`
    }
    return `This tile read ${rows} rows in ${seconds} s on its last run.`
}

export interface QueryScanDashboardEntry {
    tileId: number
    shortId: InsightShortId
    name: string
    findingCount: number
}

/** The insights on a dashboard whose last fresh run has advice for the viewer. */
export function queryScanDashboardEntries(tiles: DashboardTile<QueryBasedInsightModel>[]): QueryScanDashboardEntry[] {
    const entries: QueryScanDashboardEntry[] = []
    for (const tile of tiles) {
        const insight = tile.insight
        if (!insight || insight.deleted) {
            continue
        }
        // A killed run has no result to carry the scan, so it arrives on the query status instead.
        const summary: QueryBasedInsightModel['query_scan'] = insight.query_scan ?? insight.query_status?.query_scan
        if (summary?.mode !== 'show') {
            continue
        }
        const findingCount = queryScanFindings(summary.warnings).length
        if (findingCount === 0) {
            continue
        }
        entries.push({
            tileId: tile.id,
            shortId: insight.short_id,
            name: insight.name || insight.derived_name || 'Untitled',
            findingCount,
        })
    }
    return entries
}
