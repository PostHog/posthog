import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { EvaluationReportStoredMetrics } from '../types'
import { type ReportHeadline, headlineChange } from './reportHeadline'
import { isPassFailOutput, reportResultMetrics } from './reportMetrics'

export interface ReportStat {
    label: string
    value: string
    detail?: string
    /** Colors the detail, for a change against the previous report. */
    detailClassName?: string
}

const MAX_STATS = 4

/** The report's numbers as a row of stats: the headline rate, the result count, then each outcome. */
export function reportStats(metrics: EvaluationReportStoredMetrics, headline: ReportHeadline | null): ReportStat[] {
    const stats: ReportStat[] = []
    if (headline) {
        const change = headlineChange(headline)
        stats.push({
            label: headline.label,
            value: `${headline.value.toFixed(1)}%`,
            detail: change
                ? `${change.change > 0 ? '▲' : '▼'} ${Math.abs(change.change).toFixed(1)}pp vs previous`
                : 'No change vs previous',
            detailClassName: change?.className,
        })
    }
    if (metrics.total_runs != null) {
        stats.push({
            label: 'Results',
            value: humanFriendlyNumber(metrics.total_runs),
            detail:
                metrics.previous_total_runs != null
                    ? `${humanFriendlyNumber(metrics.previous_total_runs)} previously`
                    : 'In this period',
        })
    }
    // A share of all results beside the pass rate reads as a second, conflicting rate, so pass/fail leaves it out.
    const showShare = !isPassFailOutput(metrics)
    for (const { label, count, rate } of reportResultMetrics(metrics)) {
        if (count != null && stats.length < MAX_STATS) {
            stats.push({
                label,
                value: humanFriendlyNumber(count),
                detail: showShare && rate != null ? `${rate.toFixed(1)}% of results` : undefined,
            })
        }
    }
    return stats
}
