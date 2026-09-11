import { humanFriendlyNumber } from 'lib/utils/numbers'

import { QueryScanStatus, QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { DashboardTile, InsightShortId, QueryBasedInsightModel } from '~/types'

// The query viewset has no generated client, so this mirrors `QueryScanResponseSerializer` in
// `posthog/api/query.py`.
export interface QueryScanApiResponse {
    status: QueryScanStatus
    warnings: QueryScanWarning[]
    range_share: number | null
    project_share: number | null
    killed: boolean
}

export interface QueryScanState {
    summary: QueryScanSummary
    findings: QueryScanWarning[]
    cacheKey: string | null
}

export interface QueryScanPollResult {
    cacheKey: string
    scan: QueryScanApiResponse
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
        return { summary, findings: queryScanFindings(carrier?.warnings), cacheKey }
    }
    const { scan } = polled
    return {
        summary: {
            ...summary,
            status: scan.status,
            range_share: scan.range_share ?? undefined,
            project_share: scan.project_share ?? undefined,
            killed: scan.killed,
        },
        findings: [...queryScanFindings(carrier?.warnings), ...scan.warnings],
        cacheKey,
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

export function showQueryScanTag(findings: QueryScanWarning[], showAdvice: boolean): boolean {
    return showAdvice && findings.length > 0
}

// A `filters` finding is fixed on the insight's date range, not in the SQL, so there is nothing in
// the query for the assistant to change.
export function fixableQueryScanFindings(findings: QueryScanWarning[]): QueryScanWarning[] {
    return findings.filter((finding) => finding.reason !== 'filters')
}

// The goal and standing rules the assistant reads. These mirror `ASSISTANT_GOAL` and
// `ASSISTANT_RULES` in `posthog/query_scan/findings.py` word for word, so the "Fix with AI" message
// and the server-side `<query_scan_warning>` block read the same.
const ASSISTANT_GOAL =
    'Help me get what this query is trying to find, as fast as possible. Start by saying in one sentence what ' +
    'you think the query is trying to find. If you cannot tell, or if a faster version would answer a different ' +
    'question, ask me before rewriting. Otherwise propose the rewrite.'

const ASSISTANT_RULES =
    'The events table is sorted by project, day and event name, so a query is fast when it bounds `timestamp` ' +
    'and names events; property filters and persons joins do not narrow the read. Use relative time bounds, ' +
    'never a calendar date. Never invent event names, property values or dates; use only names seen in results ' +
    "or given by the person. Run at most the one exploration query a finding's guidance names, always with a " +
    'recent time bound and a LIMIT, and none when the guidance says none. Propose the rewritten query and label ' +
    'every change as same answer, narrower, or different. When a change would alter the answer and it is unclear ' +
    'whether that is acceptable, ask instead of choosing.'

function queryScanLead(summary: QueryScanSummary): string {
    const rows = formatRows(summary.rows_read)
    const seconds = formatSeconds(summary.duration_ms)
    if (summary.killed) {
        return `ClickHouse stopped this query after ${seconds} s, having read ${rows} rows.`
    }
    return `This query read ${rows} rows in ${seconds} s.`
}

function queryScanShareLines(summary: QueryScanSummary): string[] {
    const lines: string[] = []
    if (typeof summary.range_share === 'number') {
        lines.push(`It read about ${Math.round(summary.range_share * 100)}% of the events in this date range.`)
    }
    if (typeof summary.project_share === 'number') {
        lines.push(`It read about ${Math.round(summary.project_share * 100)}% of the project's events.`)
    }
    return lines
}

function queryScanFindingLine(finding: QueryScanWarning): string {
    const head = finding.reason ? `${finding.kind} (${finding.reason})` : finding.kind
    const parts = [`${head}:`]
    if (finding.evidence) {
        parts.push(finding.evidence)
    }
    parts.push(finding.fix)
    return `- ${parts.join(' ')}`
}

/** The message "Fix with AI" sends to the assistant, as the person's own (untrusted) message. */
export function queryScanAssistantPrompt(summary: QueryScanSummary, findings: QueryScanWarning[]): string {
    return [
        ASSISTANT_GOAL,
        '',
        queryScanLead(summary),
        ...queryScanShareLines(summary),
        ...findings.map(queryScanFindingLine),
        '',
        ASSISTANT_RULES,
    ].join('\n')
}

export interface QueryScanDashboardEntry {
    tileId: number
    shortId: InsightShortId
    name: string
    findingCount: number
}

export interface QueryScanDashboardSummary {
    entries: QueryScanDashboardEntry[]
    /** Tracks which tiles are slow and how much they have to change, so a dismissed banner returns when that set moves. */
    signature: string
}

/** The insights on a dashboard whose last fresh run has advice for the viewer. */
export function queryScanDashboardSummary(tiles: DashboardTile<QueryBasedInsightModel>[]): QueryScanDashboardSummary {
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
    return {
        entries,
        signature: entries
            .map((entry) => `${entry.tileId}:${entry.findingCount}`)
            .sort()
            .join(','),
    }
}
