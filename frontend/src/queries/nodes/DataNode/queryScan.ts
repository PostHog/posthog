import { humanFriendlyNumber } from 'lib/utils/numbers'

import { QueryScanAnalysis, QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { DashboardTile, InsightShortId } from '~/types'

export interface QueryScanState {
    summary: QueryScanSummary
    findings: QueryScanWarning[]
    cacheKey: string | null
    /** The message "Fix with AI" sends, built by the backend. Null when nothing in the query can be fixed. */
    assistantPrompt: string | null
}

export function queryScanHasActionableFinding(findings: QueryScanWarning[]): boolean {
    return findings.some((finding) => finding.actionable)
}

export interface QueryScanPollResult {
    cacheKey: string
    analysis: QueryScanAnalysis
}

interface ScanCarrier {
    query_scan?: QueryScanSummary
    cache_key?: string
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

export function resolveQueryScan(
    response: unknown,
    responseErrorObject: unknown,
    polled: QueryScanPollResult | null
): QueryScanState | null {
    const carrier = asCarrier(response) ?? errorScanCarrier(responseErrorObject)
    const stored = carrier?.query_scan
    if (!stored) {
        return null
    }
    const cacheKey = typeof carrier?.cache_key === 'string' ? carrier.cache_key : null
    // A poll outlives the run that started it, so a result for an earlier query would otherwise
    // decorate whatever response is on screen when it lands.
    const summary = polled && polled.cacheKey === cacheKey ? { ...stored, analysis: polled.analysis } : stored
    const findings = summary.analysis?.findings ?? []
    return {
        summary,
        findings,
        cacheKey,
        assistantPrompt: summary.analysis?.assistant_prompt ?? null,
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
    if (typeof summary.analysis?.range_share === 'number') {
        const percent = Math.round(summary.analysis.range_share * 100)
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

/** The insights on a dashboard whose last fresh run has advice the viewer can act on. */
export function queryScanDashboardEntries(tiles: DashboardTile[]): QueryScanDashboardEntry[] {
    const entries: QueryScanDashboardEntry[] = []
    for (const tile of tiles) {
        const insight = tile.insight
        if (!insight || insight.deleted) {
            continue
        }
        // A killed run has no result to carry the scan, so it arrives on the query status instead.
        const summary = insight.query_scan ?? insight.query_status?.query_scan
        const findingCount = (summary?.analysis?.findings ?? []).filter((finding) => finding.actionable).length
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
