import { getSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { useEffect, useRef } from 'react'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/columns/SeriesColumn'
import { IndexedTrendResult } from 'scenes/trends/types'

import { TrendsFilter } from '~/queries/schema'
import { ChartDisplayType } from '~/types'

type InsightLegendRowProps = {
    hiddenLegendKeys: Record<string, boolean | undefined>
    rowIndex: number
    item: IndexedTrendResult
    hasMultipleSeries: boolean
    toggleVisibility: (index: number) => void
    compare?: boolean | null
    display?: ChartDisplayType | null
    trendsFilter?: TrendsFilter | null
    highlighted: boolean
}

export function InsightLegendRow({
    hiddenLegendKeys,
    rowIndex,
    item,
    hasMultipleSeries,
    toggleVisibility,
    compare,
    display,
    trendsFilter,
    highlighted,
}: InsightLegendRowProps): JSX.Element {
    const highlightStyle: Record<string, any> = highlighted
        ? {
              style: { backgroundColor: getSeriesColor(item.seriesIndex, false, true) },
          }
        : {}

    const rowRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [highlighted])

    return (
        <div key={item.id} className="InsightLegendMenu-item p-2 flex flex-row" ref={rowRef} {...highlightStyle}>
            <div className="grow">
                <LemonCheckbox
                    className="text-xs mr-4"
                    color={getSeriesColor(item.seriesIndex, compare)}
                    checked={!hiddenLegendKeys[rowIndex]}
                    onChange={() => toggleVisibility(rowIndex)}
                    fullWidth
                    label={
                        <InsightLabel
                            key={item.id}
                            seriesColor={getSeriesColor(item.seriesIndex, compare)}
                            action={item.action}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            hasMultipleSeries={hasMultipleSeries}
                            breakdownValue={item.breakdown_value === '' ? 'None' : item.breakdown_value?.toString()}
                            compareValue={compare ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={item?.filter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                            hideIcon
                        />
                    }
                />
            </div>
            {display === ChartDisplayType.ActionsPie && (
                <div className="text-muted grow-0">
                    {formatAggregationAxisValue(trendsFilter, item.aggregated_value)}
                </div>
            )}
        </div>
    )
}
