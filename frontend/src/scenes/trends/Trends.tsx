import React from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { PersonsModal } from './PersonsModal'
import { ActionsPie, ActionsLineGraph, ActionsHorizontalBar } from './viz'
import { SaveCohortModal } from './SaveCohortModal'
import { trendsLogic } from './trendsLogic'
import { ChartDisplayType, InsightType, ItemMode } from '~/types'
import { InsightsTable } from 'scenes/insights/views/InsightsTable'
import { personsModalLogic } from './personsModalLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { WorldMap } from 'scenes/insights/views/WorldMap'
import { BoldNumber } from 'scenes/insights/views/BoldNumber'
import { LemonButton } from '@posthog/lemon-ui'

interface Props {
    view: InsightType
}

export function TrendInsight({ view }: Props): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { insightProps } = useValues(insightLogic)
    const { cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)
    const {
        filters: _filters,
        loadMoreBreakdownUrl,
        breakdownValuesLoading,
        showModalActions,
        aggregationTargetLabel,
    } = useValues(trendsLogic(insightProps))
    const { loadMoreBreakdownValues } = useActions(trendsLogic(insightProps))
    const { showingPeople } = useValues(personsModalLogic)
    const { saveCohortWithUrl } = useActions(personsModalLogic)
    const { reportCohortCreatedFromPersonsModal } = useActions(eventUsageLogic)

    const renderViz = (): JSX.Element | undefined => {
        if (
            !_filters.display ||
            _filters.display === ChartDisplayType.ActionsLineGraph ||
            _filters.display === ChartDisplayType.ActionsLineGraphCumulative ||
            _filters.display === ChartDisplayType.ActionsBar
        ) {
            return <ActionsLineGraph />
        }
        if (_filters.display === ChartDisplayType.BoldNumber) {
            return <BoldNumber />
        }
        if (_filters.display === ChartDisplayType.ActionsTable) {
            return (
                <BindLogic logic={trendsLogic} props={{ dashboardItemId: null, view, filters: null }}>
                    <InsightsTable
                        embedded
                        showTotalCount
                        filterKey={`trends_${view}`}
                        canEditSeriesNameInline={insightMode === ItemMode.Edit}
                        isMainInsightView={true}
                    />
                </BindLogic>
            )
        }
        if (_filters.display === ChartDisplayType.ActionsPie) {
            return <ActionsPie />
        }
        if (_filters.display === ChartDisplayType.ActionsBarValue) {
            return <ActionsHorizontalBar />
        }
        if (_filters.display === ChartDisplayType.WorldMap) {
            return <WorldMap />
        }
    }

    return (
        <>
            {(_filters.actions || _filters.events) && (
                <div
                    className={
                        _filters.display !== ChartDisplayType.ActionsTable &&
                        _filters.display !== ChartDisplayType.WorldMap &&
                        _filters.display !== ChartDisplayType.BoldNumber
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
            <PersonsModal
                visible={showingPeople && !cohortModalVisible}
                view={view}
                filters={_filters}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
                showModalActions={showModalActions}
                aggregationTargetLabel={aggregationTargetLabel}
            />
            <SaveCohortModal
                visible={cohortModalVisible}
                onOk={(title: string) => {
                    saveCohortWithUrl(title)
                    setCohortModalVisible(false)
                    reportCohortCreatedFromPersonsModal(_filters)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
        </>
    )
}
