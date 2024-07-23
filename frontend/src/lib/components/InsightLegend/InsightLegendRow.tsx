import { useActions, useValues } from 'kea'
import { getSeriesBackgroundColor, getTrendLikeSeriesColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { useEffect, useRef } from 'react'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/columns/SeriesColumn'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType } from '~/types'

import { shouldHighlightThisRow } from './utils'

type InsightLegendRowProps = {
    rowIndex: number
    item: IndexedTrendResult
    totalItems: number
}

export function InsightLegendRow({ rowIndex, item, totalItems }: InsightLegendRowProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { insightProps, highlightedSeries } = useValues(insightLogic)
    const { display, trendsFilter, breakdownFilter, isSingleSeries, hiddenLegendIndexes } = useValues(
        trendsDataLogic(insightProps)
    )
    const { toggleHiddenLegendIndex } = useActions(trendsDataLogic(insightProps))

    const highlighted = shouldHighlightThisRow(rowIndex, highlightedSeries, hiddenLegendIndexes)
    const highlightStyle: Record<string, any> = highlighted
        ? {
              style: { backgroundColor: getSeriesBackgroundColor(item.seriesIndex) },
          }
        : {}

    const rowRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (highlighted && rowRef.current) {
            rowRef.current.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
        }
    }, [highlighted])

    const formattedBreakdownValue = formatBreakdownLabel(
        item.breakdown_value,
        breakdownFilter,
        cohorts,
        formatPropertyValueForDisplay
    )

    const isPrevious = !!item.compare && item.compare_label === 'previous'
    const adjustedIndex = isPrevious ? item.seriesIndex - totalItems / 2 : item.seriesIndex

    return (
        <div key={item.id} className="InsightLegendMenu-item p-2 flex flex-row" ref={rowRef} {...highlightStyle}>
            <div className="grow">
                <LemonCheckbox
                    className="text-xs mr-4"
                    color={getTrendLikeSeriesColor(adjustedIndex, isPrevious)}
                    checked={!hiddenLegendIndexes.includes(rowIndex)}
                    onChange={() => toggleHiddenLegendIndex(rowIndex)}
                    fullWidth
                    label={
                        <InsightLabel
                            key={item.id}
                            seriesColor={getTrendLikeSeriesColor(adjustedIndex, isPrevious)}
                            action={item.action}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            hasMultipleSeries={!isSingleSeries}
                            breakdownValue={formattedBreakdownValue}
                            compareValue={isPrevious ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={breakdownFilter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
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
