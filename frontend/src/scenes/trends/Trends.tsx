import { useActions, useValues } from 'kea'
import { ActionsPie, ActionsLineGraph, ActionsHorizontalBar } from './viz'
import { trendsLogic } from './trendsLogic'
import { ChartDisplayType, InsightType, ItemMode } from '~/types'
import { InsightsTable, InsightsTableDataExploration } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { LemonButton } from '@posthog/lemon-ui'
import { isStickinessFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'

interface Props {
    view: InsightType
}

export function TrendInsight({ view }: Props): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps, isUsingDataExploration } = useValues(insightLogic)
    const { filters: _filters, loadMoreBreakdownUrl, breakdownValuesLoading } = useValues(trendsLogic(insightProps))
    const { loadMoreBreakdownValues } = useActions(trendsLogic(insightProps))
    const display = isTrendsFilter(_filters) || isStickinessFilter(_filters) ? _filters.display : null

    const renderViz = (): JSX.Element | undefined => {
        if (
            !display ||
            display === ChartDisplayType.ActionsLineGraph ||
            display === ChartDisplayType.ActionsLineGraphCumulative ||
            display === ChartDisplayType.ActionsAreaGraph ||
            display === ChartDisplayType.ActionsBar
        ) {
            return <ActionsLineGraph />
        }
        if (display === ChartDisplayType.BoldNumber) {
            return <BoldNumber />
        }
        if (display === ChartDisplayType.ActionsTable) {
            const ActionsTable = isUsingDataExploration ? InsightsTableDataExploration : InsightsTable
            return (
                <ActionsTable
                    embedded
                    filterKey={`trends_${view}`}
                    canEditSeriesNameInline={insightMode === ItemMode.Edit}
                    isMainInsightView={true}
                />
            )
        }
        if (display === ChartDisplayType.ActionsPie) {
            return <ActionsPie />
        }
        if (display === ChartDisplayType.ActionsBarValue) {
            return <ActionsHorizontalBar />
        }
        if (display === ChartDisplayType.WorldMap) {
            return <WorldMap />
        }
    }

    return (
        <>
            {(_filters.actions || _filters.events) && (
                <div
                    className={
                        display !== ChartDisplayType.ActionsTable &&
                        display !== ChartDisplayType.WorldMap &&
                        display !== ChartDisplayType.BoldNumber
                            ? 'trends-insights-container'
                            : undefined /* Tables, numbers, and world map don't need this padding, but graphs do */
                    }
                >
                    {renderViz()}
                </div>
            )}
            {_filters.breakdown && loadMoreBreakdownUrl && (
                <div className="my-4 flex flex-col items-center">
                    <div className="text-muted mb-2">
                        For readability, <b>not all breakdown values are displayed</b>. Click below to load them.
                    </div>
                    <LemonButton
                        onClick={loadMoreBreakdownValues}
                        loading={breakdownValuesLoading}
                        size="small"
                        type="secondary"
                    >
                        Load more breakdown values
                    </LemonButton>
                </div>
            )}
        </>
    )
}
