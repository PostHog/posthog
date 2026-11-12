import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

const PERIOD_CAPTIONS: Record<HighlightMetricApi['interval'], string> = {
    day: 'Last 7 days',
    week: 'Last week',
    month: 'Last month',
}

const PRIOR_LABELS: Record<HighlightMetricApi['interval'], string> = {
    day: 'vs prior 7 days',
    week: 'vs prior week',
    month: 'vs prior month',
}

export function pulsePeriodCaption(metric: HighlightMetricApi): string {
    return metric.reason === 'evaluation' ? 'Recent reports' : PERIOD_CAPTIONS[metric.interval]
}

export function pulsePriorLabel(metric: HighlightMetricApi): string {
    return metric.reason === 'evaluation' ? 'vs previous report' : PRIOR_LABELS[metric.interval]
}

export interface PulseChange {
    value: number | null
    unit: '%' | 'pp'
}

const RATE_SCALES: Record<string, number> = { percentage: 1, percentage_scaled: 100 }

export function pulseChange(metric: HighlightMetricApi): PulseChange {
    const scale = RATE_SCALES[metric.value_format?.format ?? '']
    if (scale) {
        const previous = metric.previous_value
        return { value: previous === null ? null : (metric.value - previous) * scale, unit: 'pp' }
    }
    return { value: metric.change_pct, unit: '%' }
}
