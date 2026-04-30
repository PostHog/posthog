import { SeriesLetter } from 'lib/components/SeriesGlyph'
import type { TooltipContext } from 'lib/hog-charts'
import { formatAggregationAxisValue, formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { getDatumTitle, SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { BreakdownFilter, CurrencyCode, DateRange, TrendsFilter } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { TrendsSeriesMeta } from './trendsSeriesMeta'

interface TrendsTooltipProps {
    context: TooltipContext<TrendsSeriesMeta>
    timezone?: string
    interval?: IntervalType
    breakdownFilter?: BreakdownFilter
    dateRange?: DateRange
    trendsFilter?: TrendsFilter | null
    formula?: string | null
    showPercentView?: boolean
    isPercentStackView?: boolean
    baseCurrency?: CurrencyCode
    groupTypeLabel?: string
    formatCompareLabel?: (label: string, dateLabel?: string) => string
    onRowClick?: (datum: SeriesDatum) => void
}

/** Bridges hog-charts TooltipContext to the legacy InsightTooltip.
 *  Once hog-charts fully replaces Chart.js, we can refactor InsightTooltip
 *  to consume TooltipContext directly and remove this adapter. */
export function TrendsTooltip({
    context,
    timezone,
    interval,
    breakdownFilter,
    dateRange,
    trendsFilter,
    formula,
    showPercentView,
    isPercentStackView,
    baseCurrency,
    groupTypeLabel,
    formatCompareLabel,
    onRowClick,
}: TrendsTooltipProps): React.ReactElement {
    // TODO: CI bands and moving-average datasets aren't yet built in the hog-charts path. When they
    // are, the bridge (or TrendsLineChart) will need to mark them as non-tooltip rows — legacy
    // Chart.js path used a `hideTooltip: true` flag on the dataset for this.
    const seriesData: SeriesDatum[] = context.seriesData.map((entry, idx) => {
        const meta = entry.series.meta ?? {}
        return {
            id: idx,
            dataIndex: context.dataIndex,
            datasetIndex: idx,
            order: meta.order ?? idx,
            label: entry.series.label,
            color: entry.color,
            count: entry.value,
            action: meta.action,
            breakdown_value: meta.breakdown_value,
            compare_label: meta.compare_label,
            date_label: meta.days?.[context.dataIndex],
            filter: meta.filter,
        }
    })

    const date = context.seriesData[0]?.series.meta?.days?.[context.dataIndex]

    const renderCount = (value: number): string => {
        if (showPercentView) {
            // Stickiness percent view: value is already a percentage.
            return `${value.toFixed(1)}%`
        }
        if (!isPercentStackView) {
            return formatAggregationAxisValue(trendsFilter, value, baseCurrency)
        }
        return formatPercentStackAxisValue(trendsFilter, value, isPercentStackView, baseCurrency)
    }

    return (
        <InsightTooltip
            date={date}
            timezone={timezone}
            seriesData={seriesData}
            breakdownFilter={breakdownFilter}
            interval={interval}
            dateRange={dateRange}
            formatCompareLabel={formatCompareLabel}
            groupTypeLabel={groupTypeLabel}
            onClose={context.onUnpin ?? (() => {})}
            renderSeries={(value, datum) => {
                const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
                const hasMultipleSeries = seriesData.length > 1

                if (hasBreakdown && !hasMultipleSeries) {
                    const title = getDatumTitle(datum, breakdownFilter, formatCompareLabel)
                    return <div className="datum-label-column">{title}</div>
                }

                return (
                    <div className="datum-label-column">
                        {!formula && (
                            <SeriesLetter
                                className="mr-2"
                                hasBreakdown={hasBreakdown}
                                seriesIndex={datum.action?.order ?? datum.id}
                                seriesColor={datum.color}
                            />
                        )}
                        {value}
                    </div>
                )
            }}
            renderCount={renderCount}
            onRowClick={onRowClick}
            hideInspectActorsSection={!onRowClick}
        />
    )
}
