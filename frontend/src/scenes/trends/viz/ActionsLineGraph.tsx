import React from 'react'
import { LineGraph } from '../../insights/views/LineGraph/LineGraph'
import { useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { InsightEmptyState } from '../../insights/EmptyStates'
import { ChartDisplayType, ChartParams, GraphType, InsightType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, isMultiSeriesFormula } from 'lib/utils'
import { openPersonsModal } from '../persons-modal/PersonsModal'
import { urlsForDatasets } from '../persons-modal/persons-modal-utils'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

export function ActionsLineGraph({ inSharedMode = false, showPersonsModal = true }: ChartParams): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = trendsLogic(insightProps)
    const { filters, indexedResults, incompletenessOffsetFromEnd, hiddenLegendKeys, labelGroupType } = useValues(logic)

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
            isInProgress={filters.insight !== InsightType.STICKINESS && incompletenessOffsetFromEnd < 0}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                !showPersonsModal || isMultiSeriesFormula(filters.formula)
                    ? undefined
                    : (payload) => {
                          const { index, points, crossDataset } = payload

                          const dataset = points.referencePoint.dataset
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          if (!dataset) {
                              return
                          }

                          const urls = urlsForDatasets(crossDataset, index)

                          if (urls?.length) {
                              const title =
                                  filters.shown_as === 'Stickiness' ? (
                                      <>
                                          <PropertyKeyInfo value={label || ''} disablePopover /> stickiness on day {day}
                                      </>
                                  ) : (
                                      (label: string) => (
                                          <>
                                              {label} on{' '}
                                              <DateDisplay
                                                  interval={filters.interval || 'day'}
                                                  date={day?.toString() || ''}
                                              />
                                          </>
                                      )
                                  )

                              openPersonsModal({
                                  urls,
                                  urlsIndex: crossDataset?.findIndex((x) => x.id === dataset.id) || 0,
                                  title,
                              })
                          }
                      }
            }
        />
    ) : (
        <InsightEmptyState />
    )
}
