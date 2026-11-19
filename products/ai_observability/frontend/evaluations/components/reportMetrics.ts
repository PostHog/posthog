import type { EvaluationOutputType, EvaluationReportStoredMetrics } from '../types'
import type { ReportResultSegment } from './ReportResultBar'

const RESULT_ORDER: Record<EvaluationOutputType, string[]> = {
    boolean: ['pass', 'fail', 'na'],
    numeric: ['pass', 'fail', 'na'],
    categorical: ['pass', 'fail', 'na'],
    sentiment: ['positive', 'neutral', 'negative'],
}

export interface ReportResultMetric {
    key: string
    label: string
    count?: number
    rate?: number
}

function formatResultLabel(result: string): string {
    if (result.toLowerCase() === 'na') {
        return 'N/A'
    }
    const label = result.split('_').join(' ')
    return label.length > 0 ? `${label[0].toUpperCase()}${label.slice(1)}` : result
}

/** Pass/fail outputs lead with a pass rate; sentiment leads with its distribution. */
export function isPassFailOutput(metrics: EvaluationReportStoredMetrics): boolean {
    return metrics.output_type !== 'sentiment'
}

export function reportResultMetrics(metrics: EvaluationReportStoredMetrics): ReportResultMetric[] {
    const resultCounts = metrics.result_counts ?? {}
    const totalResults = Object.values(resultCounts).reduce((total, count) => total + count, 0)
    const calculatedResultRates: Record<string, number> = {}
    if (totalResults > 0) {
        for (const [key, count] of Object.entries(resultCounts)) {
            calculatedResultRates[key] = (count / totalResults) * 100
        }
    }
    const genericResultRates = metrics.result_rates ?? {}
    const resultRates = Object.keys(genericResultRates).length > 0 ? genericResultRates : calculatedResultRates
    const resultKeys = new Set([...Object.keys(resultCounts), ...Object.keys(resultRates)])
    const configuredOrder = RESULT_ORDER[metrics.output_type ?? 'boolean'] ?? []
    const orderedKeys = [...configuredOrder.filter((key) => resultKeys.delete(key)), ...Array.from(resultKeys).sort()]

    return orderedKeys.map((key) => ({
        key,
        label: formatResultLabel(key),
        count: resultCounts[key],
        rate: resultRates[key],
    }))
}

/** The pass rate a report stored, or one worked out from its pass and fail counts. */
export function reportPassRate(metrics: EvaluationReportStoredMetrics): number | undefined {
    if (metrics.pass_rate != null) {
        return metrics.pass_rate
    }
    const resultCounts = metrics.result_counts ?? {}
    const passCount = resultCounts.pass
    const failCount = resultCounts.fail
    if (passCount == null || failCount == null || passCount + failCount === 0) {
        return undefined
    }
    return (passCount / (passCount + failCount)) * 100
}

export function reportResultSegments(metrics: EvaluationReportStoredMetrics): ReportResultSegment[] {
    return reportResultMetrics(metrics).flatMap(({ key, label, count }) => (count ? [{ key, label, count }] : []))
}
