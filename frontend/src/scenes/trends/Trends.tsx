import { useActions, useValues } from 'kea'
import { ActionsPie, ActionsLineGraph, ActionsHorizontalBar } from './viz'
import { ChartDisplayType, InsightType, ItemMode } from '~/types'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { LemonButton } from '@posthog/lemon-ui'
import { trendsDataLogic } from './trendsDataLogic'

interface Props {
    view: InsightType
}

export function TrendInsight({ view }: Props): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps } = useValues(insightLogic)

    const { display, series, breakdown, loadMoreBreakdownUrl, breakdownValuesLoading } = useValues(
        trendsDataLogic(insightProps)
    )
    const { loadMoreBreakdownValues } = useActions(trendsDataLogic(insightProps))

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
            const ActionsTable = InsightsTable
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
            {series && (
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
            {display !== ChartDisplayType.WorldMap && // the world map doesn't need this cta
                breakdown &&
                loadMoreBreakdownUrl && (
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
