import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { teamLogic } from 'scenes/teamLogic'

import type { CurrencyCode, TrendsFilter } from '~/queries/schema/schema-general'

import type { HighlightMetricApi } from 'products/today/frontend/generated/api.schemas'

import { todayNumber } from './todayNumbers'
import { TodaySparkline, type TodayTone, useTodayTonePalette } from './TodaySparkline'

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

function TodayChange({ change, tone }: { change: number | null; tone: TodayTone }): JSX.Element | null {
    const palette = useTodayTonePalette()
    if (change === null) {
        return null
    }
    const rounded = Math.round(change)
    return (
        <span
            className="TodayChange"
            translate="no"
            // eslint-disable-next-line react/forbid-dom-props
            style={tone === 'neutral' ? undefined : { color: palette[tone] }}
        >
            {rounded === 0 ? '0%' : `${rounded > 0 ? '+' : '−'}${Math.abs(rounded)}%`}
        </span>
    )
}

export function TodayPulse({ metrics }: { metrics: HighlightMetricApi[] }): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    return (
        <ul className="TodayPulse" aria-label="Key numbers, against the period before">
            {metrics.map((metric) => {
                const tone = metric.key.startsWith('insight:') ? 'neutral' : metricTone(metric.change_pct, metric.value)
                const formatValue = metricFormatter(metric, baseCurrency)
                return (
                    <li key={metric.key} className="TodayPulse__metric">
                        {metric.url ? (
                            <LinkPrimitive
                                to={metric.url}
                                className="TodayPulse__name TodayPulse__link"
                                title={metric.name}
                                data-attr="today-pulse-insight"
                            >
                                {metric.name}
                            </LinkPrimitive>
                        ) : (
                            <span className="TodayPulse__name">{metric.name}</span>
                        )}
                        <span className="TodayPulse__row">
                            <span className="TodayPulse__value" translate="no">
                                {metric.value_format ? formatValue(metric.value) : todayNumber(metric.value)}
                            </span>
                            <TodayChange change={metric.change_pct} tone={tone} />
                            <span className="TodayPulse__spark">
                                <TodaySparkline
                                    values={metric.series}
                                    labels={seriesLabels(metric)}
                                    emphasizeLast={metric.interval === 'day' ? 7 : 1}
                                    tone={tone}
                                    formatValue={formatValue}
                                />
                            </span>
                        </span>
                    </li>
                )
            })}
        </ul>
    )
}
