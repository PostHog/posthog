import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { getSeriesBackgroundColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel, getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/columns/SeriesColumn'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { ChartDisplayType } from '~/types'

type InsightLegendRowProps = {
    item: IndexedTrendResult
}

export function InsightLegendRow({ item }: InsightLegendRowProps): JSX.Element {
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    const { insightProps, highlightedSeries, editingDisabledReason } = useValues(insightLogic)
    const {
        display,
        trendsFilter,
        breakdownFilter,
        isSingleSeries,
        getTrendsColor,
        getTrendsHidden,
        resultCustomizationBy,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden } = useActions(trendsDataLogic(insightProps))

    let highlighted = false
    if (highlightedSeries) {
        const currentKey = getTrendResultCustomizationKey(resultCustomizationBy, item)
        const highlightedKey = getTrendResultCustomizationKey(resultCustomizationBy, highlightedSeries)
        highlighted = currentKey === highlightedKey
    }
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
        allCohorts.results,
        formatPropertyValueForDisplay
    )

    const isPrevious = !!item.compare && item.compare_label === 'previous'

    const themeColor = getTrendsColor(item)
    const isHidden = getTrendsHidden(item)
    const mainColor = isPrevious ? `${themeColor}80` : themeColor

    return (
        <div key={item.id} className="InsightLegendMenu-item p-2 flex flex-row" ref={rowRef} {...highlightStyle}>
            <div className="grow">
                <LemonCheckbox
                    className="text-xs mr-4"
                    color={mainColor}
                    checked={!isHidden}
                    onChange={() => toggleResultHidden(item)}
                    fullWidth
                    label={
                        <InsightLabel
                            key={item.id}
                            seriesColor={mainColor}
                            action={item.action}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            hasMultipleSeries={!isSingleSeries}
                            breakdownValue={formattedBreakdownValue}
                            compareValue={isPrevious ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={breakdownFilter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                            hideIcon
                        />
                    }
                    disabledReason={editingDisabledReason}
                />
            </div>
            {display === ChartDisplayType.ActionsPie && (
                <div className="text-secondary grow-0">
                    {formatAggregationAxisValue(trendsFilter, item.aggregated_value)}
                </div>
            )}
        </div>
    )
}
