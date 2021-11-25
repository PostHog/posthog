import React from 'react'
import { LineGraph } from '../../insights/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART } from 'lib/constants'
import { ChartParams } from '~/types'
import { InsightType } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isMultiSeriesFormula } from 'lib/utils'

export function ActionsLineGraph({
    dashboardItemId,
    color = 'white',
    inSharedMode = false,
    showPersonsModal = true,
}: ChartParams): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { filters, indexedResults, visibilityMap } = useValues(logic)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={filters.insight === InsightType.LIFECYCLE || filters.display === ACTIONS_BAR_CHART ? 'bar' : 'line'}
            color={color}
            datasets={indexedResults}
            visibilityMap={visibilityMap}
            labels={(indexedResults[0] && indexedResults[0].labels) || []}
            isInProgress={!filters.date_to}
            dashboardItemId={dashboardItemId}
            inSharedMode={inSharedMode}
            interval={filters.interval}
            showPersonsModal={showPersonsModal}
            tooltipPreferAltTitle={filters.insight === InsightType.STICKINESS}
            onClick={
                dashboardItemId || isMultiSeriesFormula(filters.formula) || !showPersonsModal
                    ? null
                    : (point) => {
                          const { dataset, day, value: pointValue, index } = point

                          const params = {
                              action: dataset.action || 'session',
                              label: dataset.label,
                              date_from: day,
                              date_to: day,
                              filters: filters,
                              breakdown_value:
                                  dataset.breakdown_value === undefined ? dataset.status : dataset.breakdown_value,
                              saveOriginal: true,
                              pointValue,
                          }
                          if (dataset.persons_urls?.[index].url) {
                              loadPeopleFromUrl({
                                  ...params,
                                  url: dataset.persons_urls[index].url,
                              })
                          } else {
                              loadPeople(params)
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState color={color} isDashboard={!!dashboardItemId} />
    )
}
