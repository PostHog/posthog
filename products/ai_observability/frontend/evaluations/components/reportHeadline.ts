import type { EvaluationReportRun } from '../types'
import { reportPassRate, reportResultSegments } from './reportMetrics'
import type { ReportResultSegment } from './ReportResultBar'

export interface ReportHeadline {
    label: string
    /** A percentage. */
    value: number
    previous: number | null
    total: number | null
    /** False when a rise is bad news, as for the negative share. */
    higherIsBetter: boolean
    segments: ReportResultSegment[]
}

/** The number a report leads with: its pass rate, or for sentiment the negative share. */
export function reportHeadline(run: EvaluationReportRun): ReportHeadline | null {
    const metrics = run.content?.metrics ?? run.metadata
    if (!metrics || run.content?.generation_status === 'metrics_unavailable') {
        return null
    }
    const total = metrics.total_runs ?? null
    const segments = reportResultSegments(metrics)
    // An empty period stores every rate as 0, which would read as a collapse rather than "nothing to grade".
    if (total === 0 || (metrics.result_counts && !segments.some(({ key }) => key !== 'na'))) {
        return null
    }
    if (metrics.output_type === 'sentiment') {
        const value = metrics.result_rates?.negative
        return value == null
            ? null
            : {
                  label: 'Negative share',
                  value,
                  previous: metrics.previous_result_rates?.negative ?? null,
                  total,
                  higherIsBetter: false,
                  segments,
              }
    }
    const value = reportPassRate(metrics)
    return value == null
        ? null
        : {
              label: 'Pass rate',
              value,
              previous: metrics.previous_pass_rate ?? null,
              total,
              higherIsBetter: true,
              segments,
          }
}

/** The change against the previous report, with its color. Null when there is no previous report or no change. */
export function headlineChange(
    headline: ReportHeadline
): { change: number; className: 'text-success' | 'text-danger' } | null {
    const change = headline.previous == null ? null : headline.value - headline.previous
    if (change == null || Math.abs(change) < 0.05) {
        return null
    }
    return { change, className: change > 0 === headline.higherIsBetter ? 'text-success' : 'text-danger' }
}
