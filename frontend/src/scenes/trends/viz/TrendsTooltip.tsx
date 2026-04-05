import { IconX } from '@posthog/icons'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import type { TooltipContext } from 'lib/hog-charts/core/types'
import { formatAggregationAxisValue, formatPercentStackAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { getDatumTitle, SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { BreakdownFilter, DateRange, TrendsFilter } from '~/queries/schema/schema-general'
import { ActionFilter, CurrencyCode, IntervalType } from '~/types'

interface TrendsTooltipProps {
    context: TooltipContext
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
}: TrendsTooltipProps): React.ReactElement {
    const seriesData: SeriesDatum[] = context.seriesData
        .map((entry, idx) => {
            const meta = entry.series.meta ?? {}
            const days = meta.days as string[] | undefined

            return {
                id: idx,
                dataIndex: context.dataIndex,
                datasetIndex: idx,
                order: typeof meta.order === 'number' ? meta.order : idx,
                label: entry.series.label,
                color: entry.color,
                count: entry.value,
                action: meta.action as ActionFilter | undefined,
                breakdown_value: meta.breakdown_value as string | number | string[] | undefined,
                compare_label: meta.compare_label as SeriesDatum['compare_label'],
                date_label: days?.[context.dataIndex],
                filter: meta.filter as SeriesDatum['filter'],
                hideTooltip: meta.hideTooltip === true,
            }
        })
        .filter((s) => !s.hideTooltip)

    const meta = context.seriesData[0]?.series.meta ?? {}
    const days = meta.days as string[] | undefined
    const date = days?.[context.dataIndex]

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
        <div className="relative">
            {context.isPinned && context.onUnpin && (
                <button
                    type="button"
                    className="absolute top-2 right-2 z-10 p-0.5 leading-none rounded cursor-pointer hover:bg-fill-button-tertiary-hover"
                    onClick={context.onUnpin}
                >
                    <IconX className="!w-3 !h-3" />
                </button>
            )}
            <InsightTooltip
                date={date}
                timezone={timezone}
                seriesData={seriesData}
                breakdownFilter={breakdownFilter}
                interval={interval}
                dateRange={dateRange}
                formatCompareLabel={formatCompareLabel}
                groupTypeLabel={groupTypeLabel}
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
                hideInspectActorsSection
            />
        </div>
    )
}
