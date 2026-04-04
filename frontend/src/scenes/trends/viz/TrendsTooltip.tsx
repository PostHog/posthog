import { IconX } from '@posthog/icons'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import type { TooltipContext } from 'lib/hog-charts/core/types'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { BreakdownFilter, DateRange } from '~/queries/schema/schema-general'
import { ActionFilter, IntervalType } from '~/types'

interface TrendsTooltipProps {
    context: TooltipContext
    timezone?: string
    interval?: IntervalType
    breakdownFilter?: BreakdownFilter
    dateRange?: DateRange
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
}: TrendsTooltipProps): React.ReactElement {
    const seriesData: SeriesDatum[] = context.seriesData.map((entry, idx) => {
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
        }
    })

    const meta = context.seriesData[0]?.series.meta ?? {}
    const days = meta.days as string[] | undefined
    const date = days?.[context.dataIndex]

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
                renderSeries={(value, datum) => (
                    <div className="datum-label-column">
                        <SeriesLetter
                            className="mr-2"
                            hasBreakdown={datum.breakdown_value !== undefined && !!datum.breakdown_value}
                            seriesIndex={datum.action?.order ?? datum.id}
                            seriesColor={datum.color}
                        />
                        {value}
                    </div>
                )}
                renderCount={(value: number): string => formatAggregationAxisValue(null, value)}
                hideInspectActorsSection
            />
        </div>
    )
}
