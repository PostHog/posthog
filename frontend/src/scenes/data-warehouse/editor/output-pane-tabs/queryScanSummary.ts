import { humanFriendlyLargeNumber, humanizeBytes } from 'lib/utils/numbers'

import {
    PredicateIndexUsage,
    PredicateIndexVerdict,
    ScanEstimate,
    ScanEstimatePrecision,
    ScanEstimateSource,
    ScanEstimateTimeRange,
    TableScanEstimate,
} from '~/queries/schema/schema-general'

// Above this many events a query on the default 60 second limit starts to time out on a busy cluster, so
// the header switches to a warning. A round number on purpose: the estimate itself is only good to a few times.
export const LARGE_SCAN_ROWS = 1_000_000_000

export interface QueryScanSummary {
    text: string
    warn: boolean
}

export function summarizeFilters(predicates: PredicateIndexUsage[]): QueryScanSummary {
    const total = predicates.length
    const scanning = predicates.filter((predicate) => predicate.verdict !== PredicateIndexVerdict.Indexed).length

    // Says an index exists, not that the filter is cheap. Whether an index drops any data depends on
    // the table's sort order and the value being compared, which the report does not look at.
    if (scanning === 0) {
        return { text: total === 1 ? '1 filter has an index' : `All ${total} filters have an index`, warn: false }
    }
    if (scanning === total) {
        return { text: total === 1 ? '1 filter reads every row' : `${total} filters read every row`, warn: true }
    }
    return { text: `${scanning} of ${total} filters read every row`, warn: true }
}

/** Tables the estimate has a row count for. */
export function estimatedTables(estimate: ScanEstimate): TableScanEstimate[] {
    return estimate.tables.filter((table) => table.rows !== undefined && table.rows !== null)
}

function describeRange(table: TableScanEstimate): string | null {
    if (table.days === undefined || table.days === null) {
        return null
    }
    if (table.time_range === ScanEstimateTimeRange.Open) {
        return 'no date range, assuming a year'
    }
    return table.days >= 2 ? `${Math.round(table.days)} days` : `${Math.round(table.days * 24)} hours`
}

export function summarizeScan(estimate: ScanEstimate): QueryScanSummary | null {
    const estimated = estimatedTables(estimate)
    if (estimated.length === 0) {
        return null
    }
    const rows = humanFriendlyLargeNumber(estimate.rows)
    // "Up to" when an indexed filter may skip data by an amount the estimate does not model.
    const qualifier = estimate.upper_bound ? 'up to' : 'about'
    const warn = estimate.rows >= LARGE_SCAN_ROWS

    const [only] = estimate.tables
    if (estimate.tables.length === 1 && only.source === ScanEstimateSource.Events) {
        return { text: `Reads ${qualifier} ${rows} events (${describeRange(only)})`, warn }
    }
    const coverage =
        estimated.length === estimate.tables.length
            ? `${estimate.tables.length} tables`
            : `${estimated.length} of ${estimate.tables.length} tables estimated`
    return { text: `Reads ${qualifier} ${rows} rows · ${coverage}`, warn }
}

/** One line for the per-table panel. */
export function describeTableScan(table: TableScanEstimate): string {
    const hasRows = table.rows !== undefined && table.rows !== null
    const hasBytes = table.bytes !== undefined && table.bytes !== null
    if (table.precision === ScanEstimatePrecision.SizeOnly && (hasRows || hasBytes)) {
        // The whole table, as the last sync left it. The tag next to it says the read itself is not modeled.
        const size = [
            hasRows ? `${humanFriendlyLargeNumber(table.rows!)} rows` : null,
            hasBytes ? humanizeBytes(table.bytes!) : null,
        ]
        return `${size.filter((part): part is string => part !== null).join(', ')} on disk`
    }
    if (hasRows) {
        const range = describeRange(table)
        const events = table.events && table.events.length > 0 ? table.events.join(', ') : null
        const detail = [range, events].filter((part): part is string => part !== null).join(', ')
        return detail
            ? `${humanFriendlyLargeNumber(table.rows!)} rows (${detail})`
            : `${humanFriendlyLargeNumber(table.rows!)} rows`
    }
    return 'no statistics yet'
}

export function summarizeQueryScan(
    predicates: PredicateIndexUsage[],
    estimate: ScanEstimate | null | undefined
): QueryScanSummary | null {
    const parts = [
        estimate ? summarizeScan(estimate) : null,
        predicates.length > 0 ? summarizeFilters(predicates) : null,
    ]
    const present = parts.filter((part): part is QueryScanSummary => part !== null)
    if (present.length === 0) {
        return null
    }
    return { text: present.map((part) => part.text).join(' · '), warn: present.some((part) => part.warn) }
}
