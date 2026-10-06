import { dayjs } from 'lib/dayjs'
import { isNotNil, isObject } from 'lib/utils/guards'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { chartOpenTarget } from 'products/signals/frontend/inbox/utils/chartOpenTarget'
import {
    asReportMetricTrendsQuery,
    reportMetricChartType,
    reportMetricRowParts,
    reportMetricWindowLabel,
    selectReportCardImpactMetric,
} from 'products/signals/frontend/inbox/utils/reportMetrics'
import type { ImpactNumberApi, ReportPageApi, SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import type { TodayFigureCardContent } from './todayFigureSources'
import { shortDate } from './todayProse'
import { lowerFirst } from './todaySignalReports'

interface TodayDailyTrend {
    data: number[]
    since: string | null
    start: string | null
}

export interface TodayImpactNumber {
    key: string
    value: string
    label: string
    window: string | null
    content: TodayFigureCardContent
    chart: { data: number[]; type: 'bar' | 'line'; partialLast: boolean } | null
}

export function dailyTrend(metric: Pick<ReportMetricApi, 'series' | 'value_at' | 'query'>): TodayDailyTrend | null {
    const series = metric.series ?? []
    if (series.length < 2 || series.some((point) => !Number.isFinite(point))) {
        return null
    }
    const query = isObject(metric.query) ? (metric.query as { source?: { interval?: unknown } }) : {}
    const daily = (query.source?.interval ?? 'day') === 'day'
    const first = series.findIndex((point) => point !== 0)
    if (!daily || !metric.value_at || first < 0) {
        return { data: series, since: null, start: null }
    }
    const start = dayjs(metric.value_at).subtract(series.length - 1 - first, 'day')
    return {
        data: series.slice(first),
        since: first > 0 ? shortDate(start) : null,
        start: start.format('YYYY-MM-DD'),
    }
}

function asSentence(label: string): string {
    const text = lowerFirst(label)
    return /[.!?]$/.test(text) ? text : `${text}.`
}

function trendRange(trend: TodayDailyTrend | null): { from: string; to: string } | null {
    if (!trend?.start) {
        return null
    }
    const lastDay = dayjs(trend.start).add(trend.data.length - 1, 'day')
    return { from: shortDate(trend.start), to: `${shortDate(lastDay)} (partial)` }
}

function shownValue(metric: ReportMetricApi, value: number | null | undefined): string | null {
    const parts = reportMetricRowParts(metric, value)
    if (!parts) {
        return null
    }
    const format = metric.value_format ?? 'number'
    const formatCarriesUnit = format === 'currency' || format.startsWith('percentage')
    const titleNamesUnit = metric.title.toLowerCase().includes(parts.unit.toLowerCase())
    return parts.unit && !formatCarriesUnit && !titleNamesUnit ? `${parts.value} ${parts.unit}` : parts.value
}

function trendWindow(metric: ReportMetricApi, trend: TodayDailyTrend | null): string | null {
    if (!trend?.start) {
        return null
    }
    const additive = reportMetricChartType(metric) === 'bar'
    const peak = Math.max(...trend.data)
    const peakDay = shortDate(dayjs(trend.start).add(trend.data.indexOf(peak), 'day'))
    const peakText = peak > 0 || !additive ? `peak ${shownValue(metric, peak)} on ${peakDay}` : null
    return [additive ? 'in total' : null, peakText].filter(Boolean).join(' · ') || null
}

function metricChart(metric: ReportMetricApi, trend: TodayDailyTrend | null): TodayImpactNumber['chart'] {
    if (!trend || trend.data.length < 2) {
        return null
    }
    return { data: trend.data, type: reportMetricChartType(metric), partialLast: !!trend.start }
}

function shownWindow(trend: TodayDailyTrend | null, window: string | null): string | null {
    if (trend?.since) {
        return `First seen ${trend.since}`
    }
    return window && capitalizeFirstLetter(window)
}

function metricNumber(report: Pick<SignalReport, 'metrics'>): TodayImpactNumber | null {
    const metric = selectReportCardImpactMetric(report.metrics)
    const value = metric ? shownValue(metric, metric.value) : null
    if (!metric || !value) {
        return null
    }
    const trend = dailyTrend(metric)
    const window = reportMetricWindowLabel(metric.query)?.toLowerCase() ?? null
    const query = asReportMetricTrendsQuery(metric.query)
    return {
        key: 'metric',
        value,
        label: asSentence(metric.title.trim()),
        window: shownWindow(trend, window),
        chart: metricChart(metric, trend),
        content: {
            kind: 'metric',
            total: value,
            at: metric.value_at ?? null,
            range: trendRange(trend),
            caption: metric.caption ?? null,
            window: trendWindow(metric, trend) ?? window,
            trend: trend?.data ?? null,
            chartType: reportMetricChartType(metric),
            link: query ? chartOpenTarget(query) : null,
        },
    }
}

function pageNumber(number: ImpactNumberApi, signals: SignalViewApi[]): TodayImpactNumber {
    const signal = signals.find((candidate) => candidate.signal_id === number.signal_id)
    return {
        key: number.key,
        value: number.value,
        label: number.sentence,
        window: null,
        chart: null,
        content: signal
            ? {
                  kind: 'signal',
                  signal,
                  excerpt: number.excerpt,
                  values: number.values.length ? number.values : undefined,
                  working: number.working ?? undefined,
              }
            : { kind: 'none' },
    }
}

export function impactNumbers(
    report: Pick<SignalReport, 'metrics'>,
    page: Pick<ReportPageApi, 'impact_numbers'> | null,
    signals: SignalViewApi[]
): TodayImpactNumber[] {
    const fromSignals = (page?.impact_numbers ?? []).map((number) => pageNumber(number, signals))
    return [metricNumber(report), ...fromSignals].filter(isNotNil)
}
