import React from 'react'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ChartDisplayType, ChartParams, GraphType, InsightType } from '~/types'
import { personsModalLogic } from '../persons-modal/personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { openPersonsModal } from '../persons-modal/PersonsModalV2'
import { dateTitle } from '../persons-modal/persons-modal-utils'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'

export function ActionsLineGraph({ inSharedMode = false, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { filters, indexedResults, incompletenessOffsetFromEnd, hiddenLegendKeys, labelGroupType } = useValues(logic)
    const { loadPeople, loadPeopleFromUrl } = useActions(personsModalLogic)

    return indexedResults &&
        indexedResults[0]?.data &&
        indexedResults.filter((result) => result.count !== 0).length > 0 ? (
        <LineGraph
            data-attr="trend-line-graph"
            type={
                filters.insight === InsightType.LIFECYCLE || filters.display === ChartDisplayType.ActionsBar
                    ? GraphType.Bar
                    : GraphType.Line
            }
            hiddenLegendKeys={hiddenLegendKeys}
            datasets={indexedResults}
            labels={(indexedResults[0] && indexedResults[0].labels) || []}
            insightNumericId={insight.id}
            inSharedMode={inSharedMode}
            labelGroupType={labelGroupType}
            showPersonsModal={showPersonsModal}
            aggregationAxisFormat={filters.aggregation_axis_format}
            tooltip={
                filters.insight === InsightType.LIFECYCLE
                    ? {
                          altTitle: 'Users',
                          altRightTitle: (_, date) => {
                              return date
                          },
                          renderSeries: (_, datum) => {
                              return capitalizeFirstLetter(datum.label?.split(' - ')?.[1] ?? datum.label ?? 'None')
                          },
                      }
                    : undefined
            }
            isCompare={!!filters.compare}
            timezone={insight.timezone}
            isInProgress={filters.insight !== InsightType.STICKINESS && incompletenessOffsetFromEnd < 0}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                !showPersonsModal || isMultiSeriesFormula(filters.formula)
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
                              action: dataset.action,
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

                          const showCountedByTag = !!crossDataset?.find(
                              ({ action }) => action?.math && action.math !== 'total'
                          )
                          const hasMultipleSeries = !!crossDataset?.find(({ action }) => action?.order)

                          const urls = crossDataset?.map((dataset) => ({
                              value: dataset.persons_urls?.[index].url || dataset.personsValues?.[index]?.url || '',
                              label: (
                                  <InsightLabel
                                      seriesColor={getSeriesColor(dataset.id)}
                                      action={dataset.action}
                                      breakdownValue={
                                          dataset.breakdown_value === '' ? 'None' : dataset.breakdown_value?.toString()
                                      }
                                      showCountedByTag={showCountedByTag}
                                      hasMultipleSeries={hasMultipleSeries}
                                  />
                              ),
                          }))

                          if (urls?.length) {
                              const selectedUrl = urls[crossDataset?.findIndex((x) => x.id === dataset.id) || 0]?.value
                              loadPeopleFromUrl({
                                  ...params,
                                  url: selectedUrl,
                              })

                              openPersonsModal({
                                  url: selectedUrl,
                                  title: dateTitle(filters.interval, day),
                                  urls,
                                  actorType: 'person',
                              })
                          } else {
                              loadPeople(params)
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState />
    )
}
