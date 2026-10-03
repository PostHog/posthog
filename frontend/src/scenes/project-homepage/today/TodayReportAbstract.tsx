import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { chartOpenTarget } from 'products/signals/frontend/inbox/utils/chartOpenTarget'
import { asReportMetricTrendsQuery, reportMetricChartType } from 'products/signals/frontend/inbox/utils/reportMetrics'

import { TodayEvidenceAge } from './TodayEvidenceAge'
import { TodayFigureMark } from './TodayFigureMark'
import { TodayInlineTrend } from './TodayInlineTrend'
import { renderedText } from './todayKeyClauses'
import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import {
    TodayDailyTrend,
    TodayOccurrences,
    TodayReportSections,
    TodayResearchNote,
    figureCardContent,
    impactSentence,
    lastOccurrence,
    markedFigures,
    signalHeadline,
    TodayFigureCardContent,
    dailyTrend,
    pganalyzeQueryCost,
    reportOccurrences,
    todayReportImpact,
} from './todayReportPresentation'

const MIN_ACTIVE_BUCKETS = 3
const MIN_OCCURRENCES = 2

interface KeyNumber {
    key: string
    value: string
    label: string
    window?: string | null
    content: TodayFigureCardContent
    chart?: { data: number[]; type: 'bar' | 'line'; partialLast?: boolean }
}

function lowerFirst(text: string): string {
    return /^[A-Z][a-z]/.test(text) ? `${text.charAt(0).toLowerCase()}${text.slice(1)}` : text
}

function sentence(label: string): string {
    const text = lowerFirst(label)
    return /[.!?]$/.test(text) ? text : `${text}.`
}

function upperFirst(text: string): string {
    return `${text.charAt(0).toUpperCase()}${text.slice(1)}`
}

function span(occurrences: TodayOccurrences): string {
    const days = Math.max(1, dayjs(occurrences.newest).diff(dayjs(occurrences.oldest), 'day') + 1)
    return days >= 14 ? `over ${Math.round(days / 7)} weeks` : days > 1 ? `over ${days} days` : 'in one day'
}

function occurrenceNumber(occurrences: TodayOccurrences): Omit<KeyNumber, 'content'> {
    const active = occurrences.buckets.filter((count) => count > 0).length
    const chart = active >= MIN_ACTIVE_BUCKETS ? { data: occurrences.buckets, type: 'bar' as const } : undefined
    const nouns: Record<TodayOccurrences['kind'], [string, string]> = {
        sessions: ['recording shows it', 'recordings show it'],
        tickets: ['support ticket', 'support tickets'],
        alerts: ['alert fired', 'alerts fired'],
    }
    const [one, many] = nouns[occurrences.kind]
    return {
        key: occurrences.kind,
        value: String(occurrences.count),
        label: `${occurrences.count === 1 ? one : many} ${span(occurrences)}`,
        chart,
    }
}

function trendRange(trend: TodayDailyTrend | null): { from: string; to: string } | null {
    if (!trend?.since || !trend.start) {
        return null
    }
    // The last bucket is the day the query ran, so it holds only part of that day.
    return {
        from: trend.since,
        to: `${dayjs(trend.start)
            .add(trend.data.length - 1, 'day')
            .format('D MMM')} (partial)`,
    }
}

function trendWindow(trend: TodayDailyTrend | null): string | null {
    if (!trend?.since || !trend.start) {
        return null
    }
    const peak = Math.max(...trend.data)
    const peakDay = dayjs(trend.start).add(trend.data.indexOf(peak), 'day').format('D MMM')
    return peak > 0 ? `in total · peak ${peak.toLocaleString('en-US')} on ${peakDay}` : 'in total'
}

export function TodayReportAbstract({
    report,
    sections,
    research,
}: {
    report: SignalReport
    sections: TodayReportSections
    research: TodayResearchNote[]
}): JSX.Element | null {
    const { signals, keyClauses } = useValues(todayReportLogic({ reportId: report.id }))
    const impact = todayReportImpact(report)
    const trend = impact ? dailyTrend(impact.metric) : null
    const impactText = impactSentence(sections)
    const pganalyzeSignal = signals.find((signal) => signal.source_product === 'pganalyze') ?? null
    const ticketSignal = signals.find((signal) => signal.source_product === 'conversations') ?? null
    const metricQuery = impact ? asReportMetricTrendsQuery(impact.metric.query) : null
    const queryCost = pganalyzeQueryCost(signals)

    const numbers: KeyNumber[] = [
        ...(impact
            ? [
                  {
                      key: 'metric',
                      value: impact.value,
                      label: impact.title,
                      window: trend?.since ? `first seen ${trend.since}` : (impact.window?.toLowerCase() ?? null),
                      chart:
                          trend && trend.data.length > 1
                              ? {
                                    data: trend.data,
                                    type: reportMetricChartType(impact.metric),
                                    partialLast: !!trend.start,
                                }
                              : undefined,
                      content: {
                          kind: 'metric' as const,
                          total: impact.value,
                          at: impact.metric.value_at ?? null,
                          range: trendRange(trend),
                          caption: impact.metric.caption ?? null,
                          window: trendWindow(trend) ?? impact.window?.toLowerCase() ?? null,
                          trend: trend?.data ?? null,
                          link: metricQuery ? chartOpenTarget(metricQuery) : null,
                      },
                  },
              ]
            : []),
        ...reportOccurrences(signals)
            .filter((occurrences) => occurrences.kind === 'tickets' && occurrences.count >= MIN_OCCURRENCES)
            .map((occurrences) => ({
                ...occurrenceNumber(occurrences),
                content: ticketSignal
                    ? { kind: 'signal' as const, signal: ticketSignal, excerpt: signalHeadline(ticketSignal) }
                    : { kind: 'none' as const },
            })),
        ...(queryCost?.hoursPerDay
            ? [
                  {
                      key: 'query-hours',
                      value: `${queryCost.hoursPerDay} ${queryCost.hoursPerDay === '1' ? 'hour' : 'hours'}`,
                      label: 'database time a day, worked out from the query’s pganalyze stats',
                      content: pganalyzeSignal
                          ? {
                                kind: 'signal' as const,
                                signal: pganalyzeSignal,
                                excerpt: signalHeadline(pganalyzeSignal),
                                values: [queryCost.averageMs, queryCost.callsPerDay],
                                working: {
                                    expression: `${queryCost.averageMs} ms × ${queryCost.callsPerDay} calls`,
                                    result: `${queryCost.exactHoursPerDay} hours a day`,
                                },
                            }
                          : { kind: 'none' as const },
                  },
              ]
            : []),
    ]

    const context = { signals, research, summary: report.summary }
    const leadIsMeasured =
        markedFigures(sections.lead, (figure) => figureCardContent(figure, { ...context, shownText: sections.lead }))
            .length > 0
    const impactMarks = markedFigures(impactText, (figure) =>
        figureCardContent(figure, { ...context, shownText: impactText })
    )

    if (numbers.length === 0 && !impactText) {
        if (leadIsMeasured) {
            return null
        }
        return (
            <Text size="sm" variant="muted" render={<p />} data-attr="today-report-abstract">
                No impact figure. The research didn’t size it.
            </Text>
        )
    }

    if (numbers.length === 0) {
        return (
            <div data-attr="today-report-abstract" data-today-figures>
                <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                    <TodayMarkedText
                        markdown={impactText}
                        marked={impactMarks}
                        reportId={report.id}
                        keyClauses={keyClauses[renderedText(impactText)]}
                    />
                </Text>
                <TodayEvidenceAge
                    marked={impactMarks}
                    reportUpdatedAt={report.updated_at}
                    lastSeen={lastOccurrence(signals)}
                />
            </div>
        )
    }

    return (
        <ul className="m-0 flex list-none flex-col gap-3 p-0" aria-label="Impact" data-attr="today-report-abstract">
            {numbers.map((number, index) => (
                <li key={number.key} className="flex flex-col gap-0.5">
                    <Text size="sm" render={<span />} className="text-pretty">
                        <TodayFigureMark
                            figure={number.value}
                            content={number.content}
                            reportId={report.id}
                            order={index}
                        >
                            <span translate="no" className="tabular-nums">
                                {number.value}
                            </span>
                        </TodayFigureMark>
                        <span>{` ${sentence(number.label)}`}</span>
                    </Text>
                    {number.window && (
                        <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-2">
                            <span>{upperFirst(number.window)}</span>
                            {number.chart && (
                                <TodayInlineTrend
                                    values={number.chart.data}
                                    type={number.chart.type}
                                    partialLast={number.chart.partialLast}
                                />
                            )}
                        </Text>
                    )}
                </li>
            ))}
        </ul>
    )
}
