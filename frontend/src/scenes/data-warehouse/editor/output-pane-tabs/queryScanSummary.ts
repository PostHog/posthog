import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import {
    EventsScanEstimate,
    PredicateIndexUsage,
    PredicateIndexVerdict,
    ScanEstimateTimeRange,
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

export function summarizeScan(estimate: EventsScanEstimate): QueryScanSummary {
    const rows = humanFriendlyLargeNumber(estimate.rows)
    const range =
        estimate.time_range === ScanEstimateTimeRange.Open
            ? 'no date range, assuming a year'
            : estimate.days >= 2
              ? `${Math.round(estimate.days)} days`
              : `${Math.round(estimate.days * 24)} hours`
    // "Up to" because property filters are not part of the estimate, so a query that has them may read less.
    return { text: `Reads up to ${rows} events (${range})`, warn: estimate.rows >= LARGE_SCAN_ROWS }
}

export function summarizeQueryScan(
    predicates: PredicateIndexUsage[],
    estimate: EventsScanEstimate | null | undefined
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
