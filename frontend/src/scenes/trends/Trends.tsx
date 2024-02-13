import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { WorldMap } from 'scenes/insights/views/WorldMap'

import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightType, ItemMode } from '~/types'

import { trendsDataLogic } from './trendsDataLogic'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from './viz'

interface Props {
    view: InsightType
    context?: QueryContext
}

export function TrendInsight({ view, context }: Props): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps, showPersonsModal } = useValues(insightLogic)

    const { display, series, breakdownFilter, loadMoreBreakdownUrl, hasBreakdownOther, breakdownValuesLoading } =
        useValues(trendsDataLogic(insightProps))
    const { loadMoreBreakdownValues, updateBreakdownFilter } = useActions(trendsDataLogic(insightProps))

    const renderViz = (): JSX.Element | undefined => {
        if (
            !display ||
            display === ChartDisplayType.ActionsLineGraph ||
            display === ChartDisplayType.ActionsLineGraphCumulative ||
            display === ChartDisplayType.ActionsAreaGraph ||
            display === ChartDisplayType.ActionsBar
        ) {
            return <ActionsLineGraph showPersonsModal={showPersonsModal} context={context} />
        }
        if (display === ChartDisplayType.BoldNumber) {
            return <BoldNumber showPersonsModal={showPersonsModal} context={context} />
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
            return <ActionsPie showPersonsModal={showPersonsModal} context={context} />
        }
        if (display === ChartDisplayType.ActionsBarValue) {
            return <ActionsHorizontalBar showPersonsModal={showPersonsModal} context={context} />
        }
        if (display === ChartDisplayType.WorldMap) {
            return <WorldMap showPersonsModal={showPersonsModal} context={context} />
        }
    }

    return (
        <>
            {series && <div className={`TrendsInsight TrendsInsight--${display}`}>{renderViz()}</div>}
            {display !== ChartDisplayType.WorldMap && // the world map doesn't need this cta
                breakdownFilter &&
                (hasBreakdownOther || loadMoreBreakdownUrl) && (
                    <div className="my-4 flex flex-col items-center px-2">
                        <div className="text-muted text-center mb-2">
                            For readability, <b>not all breakdown values are displayed</b>. Click below to load more.
                        </div>
                        <LemonButton
                            onClick={
                                hasBreakdownOther
                                    ? () =>
                                          updateBreakdownFilter({
                                              ...breakdownFilter,
                                              breakdown_limit: (breakdownFilter.breakdown_limit || 25) * 2,
                                          })
                                    : loadMoreBreakdownValues
                            }
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
