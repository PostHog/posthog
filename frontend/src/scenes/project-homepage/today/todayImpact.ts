import { dayjs } from 'lib/dayjs'
import { isNotNil, isObject } from 'lib/utils/guards'
import { humanFriendlyNumber } from 'lib/utils/numbers'
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
import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { parseAmount } from './todayFigures'
import type { TodayFigureCardContent } from './todayFigureSources'
import { shortDate } from './todayProse'
import { lowerFirst } from './todaySignalReports'
import { textOf } from './todaySignalText'

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

type OccurrenceKind = 'sessions' | 'tickets' | 'alerts'

interface Occurrences {
    count: number
    oldest: number
    newest: number
}

const MIN_TICKETS = 2
const WEEKS_FROM_DAYS = 14

export function dailyTrend(metric: Pick<ReportMetricApi, 'series' | 'value_at' | 'query'>): TodayDailyTrend | null {
    const series = metric.series ?? []
    if (series.length < 2 || series.some((point) => !Number.isFinite(point))) {
        return null
    }
    const query = isObject(metric.query) ? (metric.query as { source?: { interval?: unknown } }) : {}
    const first = series.findIndex((point) => point > 0)
    if (query.source?.interval !== 'day' || !metric.value_at || first <= 0) {
        return { data: series, since: null, start: null }
    }
    const start = dayjs(metric.value_at).subtract(series.length - 1 - first, 'day')
    return { data: series.slice(first), since: shortDate(start), start: start.format('YYYY-MM-DD') }
}

function occurrenceOf(signal: SignalViewApi): { kind: OccurrenceKind; key: string } | null {
    const extra = signal.extra
    if (signal.source_product === 'replay_vision' || signal.source_product === 'session_replay') {
        const session = textOf(extra.session_id)
        return session ? { kind: 'sessions', key: session } : null
    }
    if (signal.source_product === 'conversations' || signal.source_product === 'zendesk') {
        const ticket = typeof extra.ticket_number === 'number' ? String(extra.ticket_number) : signal.source_id
        return ticket ? { kind: 'tickets', key: ticket } : null
    }
    if (signal.source_product === 'analytics' && signal.source_type === 'anomaly_investigation') {
        return { kind: 'alerts', key: textOf(extra.alert_check_id) ?? signal.source_id }
    }
    return null
}

function occurrencesByKind(signals: SignalViewApi[]): Map<OccurrenceKind, Occurrences> {
    const firstSeen = new Map<OccurrenceKind, Map<string, number>>()
    for (const signal of signals) {
        const occurrence = occurrenceOf(signal)
        const time = new Date(signal.timestamp).getTime()
        if (!occurrence || !Number.isFinite(time)) {
            continue
        }
        const times = firstSeen.get(occurrence.kind) ?? new Map<string, number>()
        times.set(occurrence.key, Math.min(time, times.get(occurrence.key) ?? time))
        firstSeen.set(occurrence.kind, times)
    }
    return new Map(
        [...firstSeen].map(([kind, times]) => {
            const values = [...times.values()]
            return [kind, { count: values.length, oldest: Math.min(...values), newest: Math.max(...values) }]
        })
    )
}

export function lastOccurrence(signals: SignalViewApi[]): string | null {
    const newest = Math.max(...[...occurrencesByKind(signals).values()].map((occurrences) => occurrences.newest))
    return Number.isFinite(newest) ? new Date(newest).toISOString() : null
}

const PGANALYZE_TIME = /takes ([\d.,]+)\s*ms on average/i
const PGANALYZE_CALLS = /([\d,]+) calls in last 24h/i
const MS_PER_HOUR = 3_600_000

interface TodayQueryCost {
    signal: SignalViewApi
    averageMs: string
    callsPerDay: string
    hours: number
}

function pganalyzeQueryCost(signals: SignalViewApi[]): TodayQueryCost | null {
    for (const signal of signals) {
        const time = signal.source_product === 'pganalyze' ? signal.content.match(PGANALYZE_TIME)?.[1] : undefined
        const calls = signal.content.match(PGANALYZE_CALLS)?.[1]
        if (!time || !calls) {
            continue
        }
        const count = parseAmount(calls)
        const hours = (parseAmount(time) * count) / MS_PER_HOUR
        if (Number.isFinite(hours) && hours > 0) {
            return { signal, averageMs: time, callsPerDay: humanFriendlyNumber(count, 0), hours }
        }
    }
    return null
}

function asSentence(label: string): string {
    const text = lowerFirst(label)
    return /[.!?]$/.test(text) ? text : `${text}.`
}

function occurrenceSpan(occurrences: Occurrences): string {
    const days = Math.max(1, dayjs(occurrences.newest).diff(dayjs(occurrences.oldest), 'day') + 1)
    if (days >= WEEKS_FROM_DAYS) {
        return `over ${Math.round(days / 7)} weeks`
    }
    return days > 1 ? `over ${days} days` : 'in one day'
}

function trendRange(trend: TodayDailyTrend | null): { from: string; to: string } | null {
    if (!trend?.since || !trend.start) {
        return null
    }
    const lastDay = dayjs(trend.start).add(trend.data.length - 1, 'day')
    return { from: trend.since, to: `${shortDate(lastDay)} (partial)` }
}

function trendWindow(trend: TodayDailyTrend | null): string | null {
    if (!trend?.since || !trend.start) {
        return null
    }
    const peak = Math.max(...trend.data)
    const peakDay = shortDate(dayjs(trend.start).add(trend.data.indexOf(peak), 'day'))
    return peak > 0 ? `in total · peak ${peak.toLocaleString('en-US')} on ${peakDay}` : 'in total'
}

function metricNumber(report: Pick<SignalReport, 'metrics'>): TodayImpactNumber | null {
    const metric = selectReportCardImpactMetric(report.metrics)
    const parts = metric ? reportMetricRowParts(metric, metric.value) : null
    if (!metric || !parts) {
        return null
    }
    const trend = dailyTrend(metric)
    const window = reportMetricWindowLabel(metric.query)?.toLowerCase() ?? null
    const query = asReportMetricTrendsQuery(metric.query)
    return {
        key: 'metric',
        value: parts.value,
        label: asSentence(metric.title.trim()),
        window: trend?.since ? `First seen ${trend.since}` : window && capitalizeFirstLetter(window),
        chart:
            trend && trend.data.length > 1
                ? { data: trend.data, type: reportMetricChartType(metric), partialLast: !!trend.start }
                : null,
        content: {
            kind: 'metric',
            total: parts.value,
            at: metric.value_at ?? null,
            range: trendRange(trend),
            caption: metric.caption ?? null,
            window: trendWindow(trend) ?? window,
            trend: trend?.data ?? null,
            link: query ? chartOpenTarget(query) : null,
        },
    }
}

function ticketNumber(signals: SignalViewApi[]): TodayImpactNumber | null {
    const tickets = occurrencesByKind(signals).get('tickets')
    if (!tickets || tickets.count < MIN_TICKETS) {
        return null
    }
    const ticket = signals.find((signal) => occurrenceOf(signal)?.kind === 'tickets')
    return {
        key: 'tickets',
        value: String(tickets.count),
        label: `support tickets ${occurrenceSpan(tickets)}.`,
        window: null,
        chart: null,
        content: ticket ? { kind: 'signal', signal: ticket, excerpt: ticket.headline } : { kind: 'none' },
    }
}

function queryHoursNumber(signals: SignalViewApi[]): TodayImpactNumber | null {
    const cost = pganalyzeQueryCost(signals)
    if (!cost) {
        return null
    }
    const hours = humanFriendlyNumber(cost.hours, cost.hours < 10 ? 1 : 0)
    return {
        key: 'query-hours',
        value: `${hours} ${hours === '1' ? 'hour' : 'hours'}`,
        label: 'database time a day, worked out from the query’s pganalyze stats.',
        window: null,
        chart: null,
        content: {
            kind: 'signal',
            signal: cost.signal,
            excerpt: cost.signal.headline,
            values: [cost.averageMs, cost.callsPerDay],
            working: {
                expression: `${cost.averageMs} ms × ${cost.callsPerDay} calls`,
                result: `${cost.hours.toFixed(2)} hours a day`,
            },
        },
    }
}

export function impactNumbers(report: Pick<SignalReport, 'metrics'>, signals: SignalViewApi[]): TodayImpactNumber[] {
    return [metricNumber(report), ticketNumber(signals), queryHoursNumber(signals)].filter(isNotNil)
}
