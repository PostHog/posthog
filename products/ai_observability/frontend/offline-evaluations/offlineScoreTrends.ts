import type { ScatterSeries } from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents } from 'lib/utils/dateFilters'

import type {
    OfflineHistoryPageApi,
    OfflineHistoryPointApi,
    OfflineScorerSummaryApi,
    OfflineScorerVersionReadApi,
} from '../generated/api.schemas'

export interface OfflineDateRange {
    dateFrom?: string
    dateTo: string
}

export interface OfflineTrendPeriod {
    key: string
    label: string
    points: OfflineHistoryPointApi[]
    dateFrom?: string
    dateTo?: string
}

export interface OfflineTrendPointMeta {
    point: OfflineHistoryPointApi
    period: string
    metric: string
    percentage: boolean
}

export interface OfflineTrendPanel {
    key: string
    label: string
    series: ScatterSeries<OfflineTrendPointMeta>[]
    percentage: boolean
    elapsed: boolean
    xDomain?: [number, number]
    yDomain?: [number, number]
}

export function resolveOfflineDateRange(
    dateFrom: string | null,
    dateTo: string | null,
    now: string = dayjs().toISOString(),
    timezone: string = 'UTC'
): OfflineDateRange {
    const anchor = dayjs(now).tz(timezone)
    const resolve = (value: string, end: boolean): string => {
        if (value === 'now') {
            return anchor.toISOString()
        }
        const components = dateStringToComponents(value)
        if (components) {
            const subDay = ['hour', 'minute', 'second'].includes(components.unit)
            const relative = componentsToDayJs(components, subDay ? anchor : anchor.startOf('day'), timezone)
            const date = subDay ? relative : dayjs.tz(relative.format('YYYY-MM-DDTHH:mm:ss.SSS'), timezone)
            return (components.clip === 'End' ? date.add(1, 'millisecond') : date).toISOString()
        }
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            const date = dayjs.tz(value, timezone)
            // Resolve the next calendar midnight again so daylight-saving changes keep their local boundary.
            return (end ? dayjs.tz(date.add(1, 'day').format('YYYY-MM-DD'), timezone) : date).toISOString()
        }
        const date = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? dayjs(value) : dayjs.tz(value, timezone)
        if (!date.isValid()) {
            throw new Error('Choose a valid date range.')
        }
        return date.toISOString()
    }
    const range = {
        dateFrom: dateFrom && dateFrom !== 'all' ? resolve(dateFrom, false) : undefined,
        dateTo: dateTo ? resolve(dateTo, true) : anchor.toISOString(),
    }
    if (range.dateFrom && range.dateFrom >= range.dateTo) {
        throw new Error('The end of the date range must be after the start.')
    }
    return range
}

export function previousOfflinePeriod(range: OfflineDateRange): OfflineDateRange | null {
    if (!range.dateFrom) {
        return null
    }
    const duration = dayjs(range.dateTo).valueOf() - dayjs(range.dateFrom).valueOf()
    return { dateFrom: dayjs(range.dateFrom).subtract(duration, 'millisecond').toISOString(), dateTo: range.dateFrom }
}

export function offlineScoreMetricLabel(scorer: OfflineScorerVersionReadApi): string {
    if (scorer.kind === 'numeric') {
        return 'Mean score'
    }
    if (scorer.kind === 'boolean') {
        return `${'true_label' in scorer.config ? scorer.config.true_label || 'True' : 'True'} rate`
    }
    return 'Category rates'
}

export function formatOfflineScore(summary: OfflineScorerSummaryApi): string {
    if (summary.status_counts.ok === 0) {
        return 'No successful results'
    }
    if (summary.scorer.kind === 'numeric') {
        return summary.mean === null ? 'No score' : formatOfflineNumericScore(summary.mean)
    }
    if (summary.scorer.kind === 'boolean') {
        return summary.true_rate === null ? 'No score' : `${formatOfflineNumericScore(summary.true_rate * 100)}%`
    }
    return summary.categories
        .map(
            ({ label, rate }) => `${label}: ${rate === null ? 'No score' : `${formatOfflineNumericScore(rate * 100)}%`}`
        )
        .join(', ')
}

export function formatOfflineNumericScore(value: number): string {
    return value.toLocaleString(undefined, { maximumSignificantDigits: 6 })
}

export function offlineScoreConfigurationLabel(scorer: Pick<OfflineScorerVersionReadApi, 'kind' | 'config'>): string {
    const { config } = scorer
    if (scorer.kind === 'numeric') {
        return `Minimum: ${'min' in config && config.min !== null && config.min !== undefined ? formatOfflineNumericScore(config.min) : 'Unbounded'} · Maximum: ${'max' in config && config.max !== null && config.max !== undefined ? formatOfflineNumericScore(config.max) : 'Unbounded'}${'step' in config && config.step != null ? ` · Step: ${formatOfflineNumericScore(config.step)}` : ''}`
    }
    if (scorer.kind === 'boolean') {
        return `True: ${'true_label' in config ? config.true_label || 'True' : 'True'} · False: ${'false_label' in config ? config.false_label || 'False' : 'False'}`
    }
    if ('options' in config) {
        return `${config.selection_mode === 'multiple' ? 'Multiple selections' : 'Single selection'} · ${config.options.map(({ label, key }) => `${label} (${key})`).join(', ')}`
    }
    return ''
}

export function getOfflineHistoryCoverage(page: OfflineHistoryPageApi, timezone: string = 'UTC'): string {
    const dates = page.results.map(({ experiment }) => experiment.started_at).sort()
    const span = dates.length
        ? ` · ${dayjs(dates[0]).tz(timezone).format('MMM D, YYYY')} to ${dayjs(dates[dates.length - 1])
              .tz(timezone)
              .format('MMM D, YYYY')}`
        : ''
    return `${page.results.length} of ${page.count} experiment/version results${span}${page.count > page.results.length ? ' · Partial history' : ''}`
}

export function buildOfflineTrendPanels(periods: OfflineTrendPeriod[]): OfflineTrendPanel[] {
    const durations = periods.map((period) =>
        period.dateFrom && period.dateTo ? Date.parse(period.dateTo) - Date.parse(period.dateFrom) : null
    )
    const elapsed =
        periods.length > 1 && durations[0] !== null && durations.every((duration) => duration === durations[0])
    const panels = new Map<string, OfflineTrendPanel>()
    const domains = new Map<string, number[]>()
    for (const [periodIndex, period] of periods.entries()) {
        for (const point of period.points) {
            const { summary } = point
            const scorer = summary.scorer
            const configuration = `${scorer.kind}:${JSON.stringify(scorer.config)}`
            const panelKey = `${configuration}:${elapsed ? 'overlay' : period.key}`
            let panel = panels.get(panelKey)
            if (!panel) {
                panel = {
                    key: panelKey,
                    label: `${periods.length > 1 && !elapsed ? `${period.label} · ` : ''}${offlineScoreMetricLabel(scorer)}`,
                    series: [],
                    percentage: scorer.kind !== 'numeric',
                    elapsed,
                    xDomain:
                        period.dateFrom && period.dateTo
                            ? elapsed
                                ? [0, Date.parse(period.dateTo) - Date.parse(period.dateFrom)]
                                : [Date.parse(period.dateFrom), Date.parse(period.dateTo)]
                            : undefined,
                }
                panels.set(panelKey, panel)
            }
            const metrics =
                scorer.kind === 'categorical'
                    ? summary.categories.map((category) => ({
                          key: category.key,
                          label: category.label,
                          value: category.rate,
                      }))
                    : [
                          {
                              key: 'score',
                              label: offlineScoreMetricLabel(scorer),
                              value: scorer.kind === 'numeric' ? summary.mean : summary.true_rate,
                          },
                      ]
            for (const metric of metrics) {
                const key = `${period.key}:${scorer.id}:${metric.key}`
                let series = panel.series.find((candidate) => candidate.key === key)
                if (!series) {
                    series = {
                        key,
                        label: `${periods.length > 1 ? `${period.label} · ` : ''}v${scorer.version}${scorer.kind === 'categorical' ? ` · ${metric.label}` : ''}`,
                        points: [],
                        shape: periodIndex === 0 ? 'circle' : 'square',
                    }
                    panel.series.push(series)
                }
                if (metric.value === null || !Number.isFinite(metric.value)) {
                    continue
                }
                series.points.push({
                    x: Date.parse(point.experiment.started_at) - (elapsed ? Date.parse(period.dateFrom!) : 0),
                    y: metric.value,
                    label: point.experiment.name,
                    meta: { point, period: period.label, metric: metric.label, percentage: scorer.kind !== 'numeric' },
                })
                domains.set(configuration, [...(domains.get(configuration) || []), metric.value])
            }
        }
    }
    for (const [key, panel] of panels) {
        const configuration = key.slice(0, key.lastIndexOf(':'))
        const values = domains.get(configuration) || []
        if (panel.percentage) {
            panel.yDomain = [0, 1]
        } else if (values.length) {
            const min = Math.min(...values)
            const max = Math.max(...values)
            const padding = (max - min || Math.abs(max) || 1) * 0.05
            panel.yDomain = [min - padding, max + padding]
        }
    }
    return [...panels.values()]
}
