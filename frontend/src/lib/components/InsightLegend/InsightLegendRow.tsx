import { useActions, useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
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
}

export function InsightLegendRow({ rowIndex, item }: InsightLegendRowProps): JSX.Element {
    const { cohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { insightProps, hiddenLegendKeys, highlightedSeries } = useValues(insightLogic)
    const { toggleVisibility } = useActions(insightLogic)
    const { compare, display, trendsFilter, breakdownFilter, isSingleSeries } = useValues(trendsDataLogic(insightProps))

    const highlighted = shouldHighlightThisRow(hiddenLegendKeys, rowIndex, highlightedSeries)
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

    const formattedBreakdownValue = formatBreakdownLabel(
        cohorts,
        formatPropertyValueForDisplay,
        item.breakdown_value,
        breakdownFilter?.breakdown,
        breakdownFilter?.breakdown_type,
        breakdownFilter?.breakdown_histogram_bin_count !== undefined
    )

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
                            hasMultipleSeries={!isSingleSeries}
                            breakdownValue={formattedBreakdownValue}
                            compareValue={compare ? formatCompareLabel(item) : undefined}
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
