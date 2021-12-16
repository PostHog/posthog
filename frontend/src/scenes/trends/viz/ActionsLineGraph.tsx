import React from 'react'
import { LineGraph } from '../../insights/LineGraph/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ACTIONS_BAR_CHART } from 'lib/constants'
import { ActionFilter, ChartParams, GraphType, InsightType } from '~/types'
import { personsModalLogic } from '../personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { isMultiSeriesFormula } from 'lib/utils'

export function ActionsLineGraph({
    dashboardItemId,
    color = 'white',
    inSharedMode = false,
    showPersonsModal = true,
}: ChartParams): JSX.Element | null {
    const { insightProps, isViewedOnDashboard, insight } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { filters, indexedResults, visibilityMap } = useValues(logic)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={
                filters.insight === InsightType.LIFECYCLE || filters.display === ACTIONS_BAR_CHART
                    ? GraphType.Bar
                    : GraphType.Line
            }
            color={color}
            datasets={indexedResults}
            visibilityMap={visibilityMap}
            labels={(indexedResults[0] && indexedResults[0].labels) || []}
            isInProgress={!filters.date_to}
            insightId={insight.id}
            inSharedMode={inSharedMode}
            interval={filters.interval}
            showPersonsModal={showPersonsModal}
            tooltipPreferAltTitle={filters.insight === InsightType.STICKINESS}
            isCompare={!!filters.compare}
            onClick={
                dashboardItemId || isMultiSeriesFormula(filters.formula) || !showPersonsModal
                    ? undefined
                    : (payload) => {
                          const { index, points } = payload

                          // For now, take first point when clicking a specific point.
                          // TODO: Implement case when if the entire line was clicked, show people for that entire day across actions.
                          const dataset = points.clickedPointNotLine
                              ? points.pointsIntersectingClick[0].dataset
                              : points.pointsIntersectingLine[0].dataset
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          if (!dataset) {
                              return
                          }

                          const params = {
                              action: (dataset.action || 'session') as ActionFilter | 'session',
                              label,
                              date_from: day,
                              date_to: day,
                              filters,
                              breakdown_value: points.clickedPointNotLine ? dataset.breakdown_value : undefined,
                              saveOriginal: true,
                              pointValue: dataset?.data?.[index] ?? undefined,
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
        <InsightEmptyState color={color} isDashboard={isViewedOnDashboard} />
    )
}
