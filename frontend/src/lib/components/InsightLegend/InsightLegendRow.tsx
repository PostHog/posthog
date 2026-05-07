import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { getSeriesBackgroundColor } from 'lib/colors'
import { InsightLabel } from 'lib/components/InsightLabel'
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
import { ChartDisplayType } from '~/types'

import { InsightLegendRowContextMenu } from './InsightLegendRowContextMenu'

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
        showLegendIsolateSeriesItem,
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
                        />
                    }
                    disabledReason={!canEditInsight ? 'You need editor access to modify this insight.' : undefined}
                />
            </div>
            {display === ChartDisplayType.ActionsPie && (
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
        <InsightLegendRowContextMenu
            areAllSeriesVisible={areAllSeriesVisible}
            showLegendIsolateSeriesItem={showLegendIsolateSeriesItem}
            isHidden={isHidden}
            isOnlyThisVisible={isOnlyThisVisible}
            onToggleOtherSeries={() => {
                posthog.capture('insight_legend_context_menu', {
                    action: isOnlyThisVisible ? 'show_all_series' : 'hide_other_series',
                    source: 'isolate_row',
                    series_count: indexedResults.length,
                })
                toggleOtherSeriesHidden(item)
            }}
            onToggleAllSeries={() => {
                posthog.capture('insight_legend_context_menu', {
                    action: areAllSeriesVisible ? 'hide_all_series' : 'show_all_series',
                    source: 'toggle_all_row',
                    series_count: indexedResults.length,
                })
                toggleAllResultsHidden(indexedResults, areAllSeriesVisible)
            }}
        >
            {row}
        </InsightLegendRowContextMenu>
    )
}
