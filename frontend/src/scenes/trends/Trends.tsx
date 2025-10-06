import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { TrendsCalendarHeatMap } from 'scenes/insights/views/CalendarHeatMap'
import { InsightsTable } from 'scenes/insights/views/InsightsTable/InsightsTable'
import { WorldMap } from 'scenes/insights/views/WorldMap'

import { InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightType } from '~/types'

import { trendsDataLogic } from './trendsDataLogic'
import { ActionsHorizontalBar, ActionsLineGraph, ActionsPie } from './viz'

interface Props {
    view: InsightType
    context?: QueryContext<InsightVizNode>
    embedded?: boolean
    inSharedMode?: boolean
    editMode?: boolean
}

export function TrendInsight({ view, context, embedded, inSharedMode, editMode }: Props): JSX.Element {
    const { insightProps, showPersonsModal: insightLogicShowPersonsModal } = useValues(insightLogic)
    const showPersonsModal = insightLogicShowPersonsModal && !inSharedMode

    const { display, series, breakdownFilter, hasBreakdownMore, breakdownValuesLoading } = useValues(
        trendsDataLogic(insightProps)
    )
    const { updateBreakdownFilter } = useActions(trendsDataLogic(insightProps))

    const renderViz = (): JSX.Element | undefined => {
        if (
            !display ||
            display === ChartDisplayType.ActionsLineGraph ||
            display === ChartDisplayType.ActionsLineGraphCumulative ||
            display === ChartDisplayType.ActionsAreaGraph ||
            display === ChartDisplayType.ActionsBar ||
            display === ChartDisplayType.ActionsUnstackedBar
        ) {
            return (
                <ActionsLineGraph
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
        if (display === ChartDisplayType.BoldNumber) {
            return (
                <BoldNumber
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
        if (display === ChartDisplayType.ActionsTable) {
            const ActionsTable = InsightsTable
            return (
                <ActionsTable
                    embedded
                    filterKey={`trends_${view}`}
                    canEditSeriesNameInline={editMode}
                    editMode={editMode}
                    isMainInsightView={true}
                />
            )
        }
        if (display === ChartDisplayType.ActionsPie) {
            return (
                <ActionsPie
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
        if (display === ChartDisplayType.ActionsBarValue) {
            return (
                <ActionsHorizontalBar
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
        if (display === ChartDisplayType.WorldMap) {
            return (
                <WorldMap
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
        if (display === ChartDisplayType.CalendarHeatmap) {
            return (
                <TrendsCalendarHeatMap
                    showPersonsModal={showPersonsModal}
                    context={context}
                    inCardView={embedded}
                    inSharedMode={inSharedMode}
                />
            )
        }
    }

    return (
        <>
            {series && (
                <div className={embedded ? 'InsightCard__viz' : `TrendsInsight TrendsInsight--${display}`}>
                    {renderViz()}
                </div>
            )}
            {!embedded &&
                display !== ChartDisplayType.WorldMap && // the world map doesn't need this cta
                display !== ChartDisplayType.CalendarHeatmap && // the heatmap doesn't need this cta
                breakdownFilter &&
                hasBreakdownMore && (
                    <div className="p-4">
                        <div className="text-secondary">
                            Breakdown limited to {breakdownFilter.breakdown_limit || 25} - more available
                            <LemonButton
                                onClick={() =>
                                    updateBreakdownFilter({
                                        ...breakdownFilter,
                                        breakdown_limit: (breakdownFilter.breakdown_limit || 25) * 2,
                                    })
                                }
                                loading={breakdownValuesLoading}
                                size="xsmall"
                                type="secondary"
                                className="inline-block ml-2"
                            >
                                Set to {(breakdownFilter.breakdown_limit || 25) * 2}
                            </LemonButton>
                        </div>
                    </div>
                )}
        </>
    )
}
