import React from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { PersonsModal } from './PersonsModal'
import { ActionsPie, ActionsLineGraph, ActionsHorizontalBar } from './viz'
import { SaveCohortModal } from './SaveCohortModal'
import { trendsLogic } from './trendsLogic'
import { ChartDisplayType, InsightType, ItemMode } from '~/types'
import { InsightsTable } from 'scenes/insights/Views/InsightsTable'
import { Button } from 'antd'
import { personsModalLogic } from './personsModalLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { WorldMap } from 'scenes/insights/Views/WorldMap'

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
                        _filters.display !== ChartDisplayType.WorldMap
                            ? 'trends-insights-container'
                            : undefined /* Tables and world map don't need this padding, but graphs do for sizing */
                    }
                >
                    {renderViz()}
                </div>
            )}
            {_filters.breakdown && loadMoreBreakdownUrl && (
                <div className="mt text-center">
                    <div className="text-muted mb">
                        For readability, <b>not all breakdown values are displayed</b>. Click below to load them.
                    </div>
                    <div>
                        <Button
                            style={{ textAlign: 'center', marginBottom: 16 }}
                            onClick={loadMoreBreakdownValues}
                            loading={breakdownValuesLoading}
                        >
                            Load more breakdown values
                        </Button>
                    </div>
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
