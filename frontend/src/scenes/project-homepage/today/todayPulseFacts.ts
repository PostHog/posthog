import { dayjs } from 'lib/dayjs'

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
    return PERIOD_CAPTIONS[metric.interval]
}

export function pulsePriorLabel(metric: HighlightMetricApi): string {
    return PRIOR_LABELS[metric.interval]
}

function openedWhen(day: string, today: dayjs.Dayjs): string {
    const days = today.startOf('day').diff(dayjs(day).startOf('day'), 'day')
    if (days <= 0) {
        return 'today'
    }
    if (days === 1) {
        return 'yesterday'
    }
    return `on ${dayjs(day).format('MMM D')}`
}

export function pulseWhy(metric: HighlightMetricApi, today: dayjs.Dayjs = dayjs()): string | null {
    if (metric.reason === 'key_metric') {
        return 'It is a key metric for this project, set in Customer analytics.'
    }
    if (metric.reason === 'popular') {
        return 'People in this project open this insight often.'
    }
    if (metric.reason === 'watched') {
        return 'You get an alert or a subscription for this insight.'
    }
    if (metric.reason === 'built') {
        return 'You created or edited this insight recently.'
    }
    if (metric.reason !== 'routine' && metric.reason !== 'dashboard') {
        return null
    }
    const subject =
        metric.reason === 'dashboard'
            ? metric.dashboard_name
                ? `the ${metric.dashboard_name} dashboard`
                : 'its dashboard'
            : 'this insight'
    const suffix = metric.reason === 'dashboard' ? ' This is the first chart on that dashboard.' : ''
    if (!metric.last_opened) {
        return `You open ${subject} often.${suffix}`
    }
    const when = openedWhen(metric.last_opened, today)
    if (!metric.opened_days || metric.opened_days < 2) {
        return `You last opened ${subject} ${when}.${suffix}`
    }
    return `You opened ${subject} on ${metric.opened_days} of the last 14 days, most recently ${when}.${suffix}`
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
