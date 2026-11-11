import type { EvaluationReportRun } from '../types'
import { reportPassRate } from './EvaluationReportViewer'

export interface ReportHeadline {
    label: string
    /** A percentage. */
    value: number
    previous: number | null
    total: number | null
}

/** The number a report leads with: its pass rate, or for sentiment the negative share. */
export function reportHeadline(run: EvaluationReportRun): ReportHeadline | null {
    const metrics = run.content?.metrics ?? run.metadata
    if (!metrics || run.content?.generation_status === 'metrics_unavailable') {
        return null
    }
    const total = metrics.total_runs ?? null
    if (metrics.output_type === 'sentiment') {
        const value = metrics.result_rates?.negative
        return value == null
            ? null
            : { label: 'Negative share', value, previous: metrics.previous_result_rates?.negative ?? null, total }
    }
    const value = reportPassRate(metrics)
    return value == null ? null : { label: 'Pass rate', value, previous: metrics.previous_pass_rate ?? null, total }
}
