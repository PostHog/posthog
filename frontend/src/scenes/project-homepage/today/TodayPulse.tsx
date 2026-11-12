import { useActions, useValues } from 'kea'
import { type RefObject, Suspense, lazy, useLayoutEffect, useRef } from 'react'

import { IconSparkles } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { formatAggregationAxisValue } from 'lib/insights/aggregationAxisFormat'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { retryImport } from 'lib/utils/retryImport'
import { teamLogic } from 'scenes/teamLogic'

import type { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import type { HighlightMetricApi, PulseSlotApi } from 'products/today/frontend/generated/api.schemas'

import { TodayChange } from './TodayChange'
import { pulsePinLimitReason, todayHighlightsLogic } from './todayHighlightsLogic'
import { todayNumber } from './todayNumbers'
import { TodayPulseCard } from './TodayPulseCard'
import { experimentTone } from './todayPulseExperiment'
import { TodayPulseExperimentValue } from './TodayPulseExperimentValue'
import { pulseChange } from './todayPulseFacts'
import { TodayPulseHoverCard } from './TodayPulseHoverCard'
import { pulseOpenHandlers } from './todayPulseOpenHandlers'
import { pulsePlaceholderLabel, TodayPulsePlaceholder } from './TodayPulsePlaceholder'
import { productNumberPinReason } from './todayPulseProductNumbers'
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

function pulseTone(metric: HighlightMetricApi): TodayTone {
    if (metric.experiment) {
        return experimentTone(metric.experiment)
    }
    return metric.key.startsWith('insight:') ? 'neutral' : metricTone(metric.change_pct, metric.value)
}

function pulseLinkAttr(metric: HighlightMetricApi): string {
    if (metric.experiment) {
        return 'today-pulse-experiment'
    }
    return metric.key.startsWith('insight:') ? 'today-pulse-insight' : 'today-pulse-key-metric'
}

function pulseCardPinReason(
    metric: HighlightMetricApi,
    unavailableReason: string | null,
    pinnedCount: number,
    pinned: boolean
): string | undefined {
    return productNumberPinReason(metric.key) ?? unavailableReason ?? pulsePinLimitReason(pinnedCount, pinned)
}

const PERIOD_FORMATS: Record<HighlightMetricApi['interval'], string> = {
    day: 'ddd, D MMM',
    week: '[Week of] D MMM',
    month: 'MMM YYYY',
}

function emphasizedPoints(metric: HighlightMetricApi): number {
    return metric.interval === 'day' && metric.reason !== 'evaluation' ? 7 : 1
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

function cardNumber(value: number): string {
    return humanFriendlyNumber(value, Math.abs(value) >= 100 ? 0 : 2)
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

export function TodayPulse({ metrics, slots }: { metrics: HighlightMetricApi[]; slots?: PulseSlotApi[] }): JSX.Element {
    const cards =
        slots ??
        metrics.map(
            (metric): PulseSlotApi => ({
                key: metric.key,
                name: metric.name,
                status: 'ready',
                url: metric.url,
                interval: metric.interval,
            })
        )
    const { pulsePins, pulsePinsUnavailableReason, pulseHideUnavailableReason } = useValues(todayHighlightsLogic)
    const listRef = useRef<HTMLUListElement>(null)
    useSettleOnReorder(listRef, cards.map((tile) => tile.key).join('|'))
    const { baseCurrency } = useValues(teamLogic)
    const { pulseMetricOpened, pulseMetricPreviewed, hidePulseMetric, togglePulsePin } =
        useActions(todayHighlightsLogic)
    return (
        <ul ref={listRef} className="TodayPulse" aria-label="Key numbers, against the period before">
            {cards.map((slot, position) => {
                const metric = metrics.find((metric) => metric.key === slot.key)
                if (!metric) {
                    return (
                        <li
                            key={slot.key}
                            data-pulse-key={slot.key}
                            className="TodayPulse__metric"
                            aria-busy={slot.status === 'pending'}
                            aria-label={pulsePlaceholderLabel(slot)}
                        >
                            <TodayPulsePlaceholder slot={slot} />
                        </li>
                    )
                }

                const experiment = metric.experiment
                const pinned = pulsePins.some((pin) => pin.key === metric.key)
                const tone = pulseTone(metric)
                const formatValue = metric.value_format ? metricFormatter(metric, baseCurrency) : todayNumber
                const change = pulseChange(metric)
                const content = (
                    <>
                        <span className="TodayPulse__name">
                            {!pinned && <IconSparkles className="TodayPulse__suggested" aria-label="Suggested" />}
                            <span>{metric.name}</span>
                        </span>
                        {experiment ? (
                            <TodayPulseExperimentValue lift={metric.value} experiment={experiment} tone={tone} />
                        ) : (
                            <>
                                <span className="TodayPulse__row">
                                    <span className="TodayPulse__value" translate="no">
                                        {formatValue(metric.value)}
                                    </span>
                                    <TodayChange change={change.value} unit={change.unit} tone={tone} />
                                </span>
                                <span className="TodayPulse__spark">
                                    <Suspense fallback={null}>
                                        <TodaySparkline
                                            values={metric.series}
                                            labels={seriesLabels(metric)}
                                            emphasizeLast={emphasizedPoints(metric)}
                                            tone={tone}
                                        />
                                    </Suspense>
                                </span>
                            </>
                        )}
                    </>
                )
                return (
                    <li key={metric.key} data-pulse-key={metric.key} className="TodayPulse__metric">
                        <TodayPulseHoverCard
                            focusable={!metric.url}
                            onOpenChange={(open) => {
                                if (open) {
                                    pulseMetricPreviewed(metric, position)
                                }
                            }}
                            card={
                                <TodayPulseCard
                                    metric={metric}
                                    tone={tone}
                                    formatValue={metric.value_format ? formatValue : cardNumber}
                                    onOpen={() => pulseMetricOpened(metric, position)}
                                    pinned={pinned}
                                    pinDisabledReason={pulseCardPinReason(
                                        metric,
                                        pulsePinsUnavailableReason,
                                        pulsePins.length,
                                        pinned
                                    )}
                                    onTogglePin={() =>
                                        togglePulsePin(
                                            { key: metric.key, name: metric.name, dashboard_id: metric.dashboard_id },
                                            'hover_card'
                                        )
                                    }
                                    hideDisabledReason={pulseHideUnavailableReason}
                                    onHide={() => hidePulseMetric(metric, position)}
                                />
                            }
                        >
                            {metric.url ? (
                                <LinkPrimitive
                                    to={metric.url}
                                    className="TodayPulse__link"
                                    data-attr={pulseLinkAttr(metric)}
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
