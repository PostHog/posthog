import { useActions, useValues } from 'kea'
import { type RefObject, Suspense, lazy, useLayoutEffect, useRef } from 'react'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { retryImport } from 'lib/utils/retryImport'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { teamLogic } from 'scenes/teamLogic'

import type { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { todayHighlightsLogic } from './todayHighlightsLogic'
import { todayNumber } from './todayNumbers'
import { TodayPulseCard } from './TodayPulseCard'
import { TodayPulseHoverCard } from './TodayPulseHoverCard'
import { pulseOpenHandlers } from './todayPulseOpenHandlers'
import type { TodayTone } from './todayTone'

// The charts are most of the code the home page adds, so the numbers render first and the sparklines follow.
const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

const CHANGE_THRESHOLD = 3
const MIN_ABSOLUTE_CHANGE = 5

function metricTone(change: number | null, value: number): TodayTone {
    if (change === null || Math.abs(change) < CHANGE_THRESHOLD) {
        return 'neutral'
    }
    const before = value / (1 + change / 100)
    if (Math.abs(value - before) < MIN_ABSOLUTE_CHANGE) {
        return 'neutral'
    }
    return change > 0 ? 'good' : 'risk'
}

const PERIOD_FORMATS: Record<HighlightMetricApi['interval'], string> = {
    day: 'ddd, D MMM',
    week: '[Week of] D MMM',
    month: 'MMM YYYY',
}

function seriesLabels(metric: HighlightMetricApi): string[] {
    return metric.period_starts.map((start) => dayjs(start).format(PERIOD_FORMATS[metric.interval]))
}

function metricFormatter(metric: HighlightMetricApi, currency: CurrencyCode): (value: number) => string {
    const format = metric.value_format
    if (!format) {
        return humanFriendlyNumber
    }
    const trendsFilter: TrendsFilter = {
        aggregationAxisFormat: (format.format ?? undefined) as TrendsFilter['aggregationAxisFormat'],
        aggregationAxisPrefix: format.prefix ?? undefined,
        aggregationAxisPostfix: format.postfix ?? undefined,
        decimalPlaces: format.decimal_places ?? undefined,
    }
    return (value) => formatAggregationAxisValue(trendsFilter, value, currency)
}

const REORDER_MS = 220

function useSettleOnReorder(listRef: RefObject<HTMLUListElement>, order: string): void {
    const previous = useRef(order)
    useLayoutEffect(() => {
        const before = previous.current.split('|')
        previous.current = order
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            return
        }
        listRef.current?.querySelectorAll<HTMLElement>('[data-pulse-key]').forEach((tile, index) => {
            const was = before.indexOf(tile.dataset.pulseKey ?? '')
            if (was !== -1 && was !== index) {
                tile.animate(
                    [
                        { opacity: 0, transform: 'translateY(4px)' },
                        { opacity: 1, transform: 'none' },
                    ],
                    {
                        duration: REORDER_MS,
                        easing: 'cubic-bezier(0.2, 0, 0, 1)',
                    }
                )
            }
        })
    }, [order, listRef])
}

export function TodayPulse({ metrics }: { metrics: HighlightMetricApi[] }): JSX.Element {
    const listRef = useRef<HTMLUListElement>(null)
    useSettleOnReorder(listRef, metrics.map((tile) => tile.key).join('|'))
    const { baseCurrency } = useValues(teamLogic)
    const { pulseMetricOpened, pulseMetricPreviewed, hidePulseMetric, holdPulseOrder, releasePulseOrder } =
        useActions(todayHighlightsLogic)
    return (
        <ul ref={listRef} className="TodayPulse" aria-label="Key numbers, against the period before">
            {metrics.map((metric, position) => {
                const isInsight = metric.key.startsWith('insight:')
                const tone = isInsight ? 'neutral' : metricTone(metric.change_pct, metric.value)
                const formatValue = metric.value_format ? metricFormatter(metric, baseCurrency) : todayNumber
                const content = (
                    <>
                        <span className="TodayPulse__name">{metric.name}</span>
                        <span className="TodayPulse__row">
                            <span className="TodayPulse__value" translate="no">
                                {formatValue(metric.value)}
                            </span>
                            <TodayChange change={metric.change_pct} tone={tone} />
                        </span>
                        <span className="TodayPulse__spark">
                            <Suspense fallback={null}>
                                <TodaySparkline
                                    values={metric.series}
                                    labels={seriesLabels(metric)}
                                    emphasizeLast={metric.interval === 'day' ? 7 : 1}
                                    tone={tone}
                                />
                            </Suspense>
                        </span>
                    </>
                )
                return (
                    <li key={metric.key} data-pulse-key={metric.key} className="TodayPulse__metric">
                        <TodayPulseHoverCard
                            onOpenChange={(open) => {
                                if (open) {
                                    pulseMetricPreviewed(metric, position)
                                    holdPulseOrder(
                                        metric.key,
                                        metrics.map((tile) => tile.key)
                                    )
                                } else {
                                    releasePulseOrder(metric.key)
                                }
                            }}
                            card={
                                <TodayPulseCard
                                    metric={metric}
                                    tone={tone}
                                    formatValue={metric.value_format ? formatValue : humanFriendlyNumber}
                                    onOpen={() => pulseMetricOpened(metric, position)}
                                    onHide={() => hidePulseMetric(metric, position)}
                                />
                            }
                        >
                            {metric.url ? (
                                <LinkPrimitive
                                    to={metric.url}
                                    className="TodayPulse__link"
                                    data-attr={isInsight ? 'today-pulse-insight' : 'today-pulse-key-metric'}
                                    {...pulseOpenHandlers(() => pulseMetricOpened(metric, position))}
                                >
                                    {content}
                                </LinkPrimitive>
                            ) : (
                                content
                            )}
                        </TodayPulseHoverCard>
                    </li>
                )
            })}
        </ul>
    )
}
