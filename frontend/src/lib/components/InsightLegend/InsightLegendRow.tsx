import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { getSeriesBackgroundColor } from 'lib/colors'
import { captureLegendMenuAction } from 'lib/components/ChartLegendSeriesMenu/captureLegendMenuAction'
import { ChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/ChartLegendSeriesMenu'
import { InsightLabel } from 'lib/components/InsightLabel'
import { PIE_DISPLAY_TYPES } from 'lib/constants'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownLabel, getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { formatCompareLabel } from 'scenes/insights/views/InsightsTable/columns/SeriesColumn'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { IndexedTrendResult } from 'scenes/trends/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

type InsightLegendRowProps = {
    item: IndexedTrendResult
    readOnly?: boolean
}

export function InsightLegendRow({ item, readOnly = false }: InsightLegendRowProps): JSX.Element {
    const { allCohorts } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { baseCurrency } = useValues(teamLogic)

    const { insightProps, highlightedSeries, canEditInsight } = useValues(insightLogic)
    const {
        display,
        trendsFilter,
        breakdownFilter,
        isSingleSeriesDefinition,
        getTrendsColor,
        getTrendsHidden,
        resultCustomizationBy,
        indexedResults,
        areAllSeriesVisible,
        legendSeriesIsolationMenuEligible,
        getIsOnlyVisibleSeriesInLegend,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleResultHidden, toggleOtherSeriesHidden, toggleAllResultsHidden } = useActions(
        trendsDataLogic(insightProps)
    )

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
    const showPathCleaningHighlight =
        breakdownFilter?.breakdown_path_cleaning && typeof formattedBreakdownValue === 'string'

    const themeColor = getTrendsColor(item)
    const isHidden = getTrendsHidden(item)
    const mainColor = isPrevious ? `${themeColor}80` : themeColor

    const isOnlyThisVisible = getIsOnlyVisibleSeriesInLegend(item)

    const showSeriesIsolationMenu = !readOnly && legendSeriesIsolationMenuEligible

    const row = (
        <div className="InsightLegendMenu-item p-2 flex flex-row" ref={rowRef} {...highlightStyle}>
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
                            hasMultipleSeries={!isSingleSeriesDefinition}
                            breakdownValue={formattedBreakdownValue}
                            compareValue={isPrevious ? formatCompareLabel(item) : undefined}
                            pillMidEllipsis={breakdownFilter?.breakdown === '$current_url'} // TODO: define set of breakdown values that would benefit from mid ellipsis truncation
                            showPathCleaningHighlight={showPathCleaningHighlight}
                            hideIcon
                            showSingleName
                            hideHogQLTagWhenCustomName
                        />
                    }
                    disabledReason={!canEditInsight ? 'You need editor access to modify this insight.' : undefined}
                />
            </div>
            {display && PIE_DISPLAY_TYPES.includes(display) && (
                <div className="text-secondary grow-0">
                    {formatAggregationAxisValue(trendsFilter, item.aggregated_value, baseCurrency)}
                </div>
            )}
        </div>
    )

    if (!showSeriesIsolationMenu) {
        return row
    }

    return (
        <ChartLegendSeriesMenu
            seriesLabel={item.label}
            seriesColor={mainColor}
            isHidden={isHidden}
            isOnlyVisible={isOnlyThisVisible}
            areAllVisible={areAllSeriesVisible}
            canIsolate={legendSeriesIsolationMenuEligible}
            showGestureHints={false}
            onToggle={() => {
                captureLegendMenuAction({
                    action: isHidden ? 'show_series' : 'hide_series',
                    source: 'toggle_row',
                    surface: 'insight_legend_table',
                    seriesCount: indexedResults.length,
                })
                toggleResultHidden(item)
            }}
            onIsolate={() => {
                captureLegendMenuAction({
                    action: isOnlyThisVisible ? 'show_all_series' : 'hide_other_series',
                    source: 'isolate_row',
                    surface: 'insight_legend_table',
                    seriesCount: indexedResults.length,
                })
                toggleOtherSeriesHidden(item)
            }}
            onToggleAll={() => {
                captureLegendMenuAction({
                    action: areAllSeriesVisible ? 'hide_all_series' : 'show_all_series',
                    source: 'toggle_all_row',
                    surface: 'insight_legend_table',
                    seriesCount: indexedResults.length,
                })
                toggleAllResultsHidden(indexedResults, areAllSeriesVisible)
            }}
        >
            {row}
        </ChartLegendSeriesMenu>
    )
}
