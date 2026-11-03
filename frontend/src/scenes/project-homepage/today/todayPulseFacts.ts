import { dayjs } from 'lib/dayjs'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

const PERIOD_CAPTIONS: Record<HighlightMetricApi['interval'], string> = {
    day: 'Last 7 days, against the 7 days before',
    week: 'Last week, against the week before',
    month: 'Last month, against the month before',
}

export function pulsePeriodCaption(metric: HighlightMetricApi): string {
    return PERIOD_CAPTIONS[metric.interval]
}

const PEAK_LABELS: Record<HighlightMetricApi['interval'], string> = {
    day: 'Top day',
    week: 'Top week',
    month: 'Top month',
}

const LATEST_PERIODS: Record<HighlightMetricApi['interval'], string> = {
    day: 'yesterday',
    week: 'last week',
    month: 'last month',
}

export interface PulsePeak {
    label: string
    value: number
    start: string
    latest: string | null
}

export function pulsePeak(metric: HighlightMetricApi): PulsePeak | null {
    let peak: PulsePeak | null = null
    const lastIndex = metric.series.length - 1
    for (const [index, value] of metric.series.entries()) {
        const start = metric.period_starts[index]
        if (start && !Number.isNaN(value) && (peak === null || value > peak.value)) {
            peak = {
                label: PEAK_LABELS[metric.interval],
                value,
                start,
                latest: index === lastIndex ? LATEST_PERIODS[metric.interval] : null,
            }
        }
    }
    return peak
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

const PERIOD_NAMES: Record<HighlightMetricApi['interval'], string> = {
    day: 'Last 7 days',
    week: 'Last week',
    month: 'Last month',
}

export function pulseComparison(metric: HighlightMetricApi, formatValue: (value: number) => string): string {
    const period = PERIOD_NAMES[metric.interval]
    const previous = metric.previous_value
    if (previous === null) {
        return period
    }
    if (metric.value === previous) {
        return `${period}, same as the period before`
    }
    return `${period}, ${metric.value > previous ? 'up' : 'down'} from ${formatValue(previous)}`
}

const PEAK_DATE_FORMATS: Record<HighlightMetricApi['interval'], string> = {
    day: 'ddd, D MMM',
    week: '[the week of] D MMM',
    month: 'MMMM YYYY',
}

export function pulsePeakNote(metric: HighlightMetricApi, formatValue: (value: number) => string): string | null {
    const peak = pulsePeak(metric)
    if (peak === null || metric.series.length < 3) {
        return null
    }
    if (peak.latest) {
        return `Best ${metric.interval} in ${metric.series.length} ${metric.interval}s`
    }
    return `Best ${metric.interval} was ${dayjs(peak.start).format(PEAK_DATE_FORMATS[metric.interval])}, at ${formatValue(peak.value)}`
}
