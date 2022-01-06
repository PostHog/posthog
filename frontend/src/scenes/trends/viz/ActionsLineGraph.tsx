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
    const { filters, indexedResults, visibilityMap, incompletenessOffsetFromEnd } = useValues(logic)
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
            insightId={insight.id}
            inSharedMode={inSharedMode}
            interval={filters.interval}
            showPersonsModal={showPersonsModal}
            tooltipPreferAltTitle={filters.insight === InsightType.STICKINESS}
            tooltip={{
                altTitle: filters.insight === InsightType.LIFECYCLE ? 'Users' : undefined,
            }}
            isCompare={!!filters.compare}
            isInProgress={filters.insight !== InsightType.STICKINESS && incompletenessOffsetFromEnd < 0}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                dashboardItemId || isMultiSeriesFormula(filters.formula) || !showPersonsModal
                    ? undefined
                    : (payload) => {
                          const { index, points, crossDataset, seriesId } = payload

                          const dataset = points.referencePoint.dataset
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
                              breakdown_value: points.clickedPointNotLine
                                  ? dataset.breakdown_value || dataset.status
                                  : undefined,
                              saveOriginal: true,
                              crossDataset,
                              seriesId,
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
