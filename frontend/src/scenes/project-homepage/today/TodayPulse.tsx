import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
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
import { TodaySparkline, type TodayTone } from './TodaySparkline'

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

export function TodayPulse({ metrics }: { metrics: HighlightMetricApi[] }): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const { pulseMetricOpened, pulseMetricPreviewed } = useActions(todayHighlightsLogic)
    return (
        <ul className="TodayPulse" aria-label="Key numbers, against the period before">
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
                            <TodaySparkline
                                values={metric.series}
                                labels={seriesLabels(metric)}
                                emphasizeLast={metric.interval === 'day' ? 7 : 1}
                                tone={tone}
                            />
                        </span>
                    </>
                )
                return (
                    <li key={metric.key} className="TodayPulse__metric">
                        <TodayPulseHoverCard
                            onOpen={() => pulseMetricPreviewed(metric, position)}
                            card={
                                <TodayPulseCard
                                    metric={metric}
                                    tone={tone}
                                    formatValue={metric.value_format ? formatValue : humanFriendlyNumber}
                                    onOpen={() => pulseMetricOpened(metric, position)}
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
