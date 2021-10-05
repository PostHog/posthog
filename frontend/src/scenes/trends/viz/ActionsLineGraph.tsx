import React from 'react'
import { LineGraph } from '../../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { LineGraphEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART } from 'lib/constants'
import { ChartParams } from '~/types'
import { ViewType } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function ActionsLineGraph({
    color = 'white',
    filters: filtersParam,
    cachedResults,
    inSharedMode = false,
    showPersonsModal = true,
    view,
}: ChartParams): JSX.Element | null {
    const { insight } = useValues(insightLogic)
    const logic = trendsLogic({
        dashboardItemId: insight?.id,
        view: view || filtersParam?.insight,
        filters: filtersParam,
        cachedResults,
    })
    const { filters, indexedResults, visibilityMap } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={filters.insight === ViewType.LIFECYCLE || filters.display === ACTIONS_BAR_CHART ? 'bar' : 'line'}
            color={color}
            datasets={indexedResults}
            visibilityMap={visibilityMap}
            labels={(indexedResults[0] && indexedResults[0].labels) || []}
            isInProgress={!filters.date_to}
            dashboardItemId={insight?.id /* used only for annotations, not to init any other logic */}
            inSharedMode={inSharedMode}
            interval={filters.interval}
            showPersonsModal={showPersonsModal}
            tooltipPreferAltTitle={filters.insight === ViewType.STICKINESS}
            onClick={
                insight?.id
                    ? null
                    : (point) => {
                          const { dataset, day } = point
                          loadPeople({
                              action: dataset.action || 'session',
                              label: dataset.label,
                              date_from: day,
                              date_to: day,
                              filters: filters,
                              breakdown_value:
                                  dataset.breakdown_value === undefined ? dataset.status : dataset.breakdown_value,
                              saveOriginal: true,
                          })
                      }
            }
        />
    ) : (
        <LineGraphEmptyState color={color} isDashboard={!!insight?.id} />
    )
}
