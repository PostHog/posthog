import React from 'react'
import { LineGraph } from 'scenes/insights/views/LineGraph/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { useActions, useValues } from 'kea'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'
import { ChartParams, GraphType, GraphDataset, EntityTypes } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter, shortTimeZone } from 'lib/utils'
import { dayjs } from 'lib/dayjs'
import { getFormattedDate } from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModalV2'
import { buildFunnelPeopleUrl } from 'scenes/trends/persons-modal/persons-modal-utils'

export function FunnelLineGraph({
    inSharedMode,
    showPersonsModal = true,
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { steps, filters, aggregationTargetLabel, incompletenessOffsetFromEnd } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)

    return (
        <LineGraph
            data-attr="trend-line-graph-funnel"
            type={GraphType.Line}
            datasets={steps as unknown as GraphDataset[] /* TODO: better typing */}
            labels={steps?.[0]?.labels ?? ([] as string[])}
            isInProgress={incompletenessOffsetFromEnd < 0}
            timezone={insight.timezone}
            insightNumericId={insight.id}
            inSharedMode={!!inSharedMode}
            showPersonsModal={showPersonsModal}
            tooltip={{
                showHeader: false,
                hideColorCol: true,
                renderSeries: (_, datum) => {
                    if (!steps?.[0]?.days) {
                        return 'Trend'
                    }
                    return (
                        getFormattedDate(steps[0].days?.[datum.dataIndex], filters.interval) +
                        ' ' +
                        (insight.timezone ? shortTimeZone(insight.timezone) : 'UTC')
                    )
                },
                renderCount: (count) => {
                    return `${count}%`
                },
            }}
            aggregationAxisFormat="percentage"
            labelGroupType={filters.aggregation_group_type_index ?? 'people'}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                !showPersonsModal
                    ? undefined
                    : (payload) => {
                          const { points, index } = payload
                          const dataset = points.clickedPointNotLine
                              ? points.pointsIntersectingClick[0].dataset
                              : points.pointsIntersectingLine[0].dataset
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          const props = {
                              action: { id: index, name: label ?? null, properties: [], type: EntityTypes.ACTIONS },
                              label: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${dayjs(
                                  label
                              ).format('MMMM Do YYYY')}`, // TODO: Remove
                              date_from: day ?? '',
                              date_to: day ?? '',
                              filters: filters,
                              saveOriginal: true, // TODO: Remove
                              pointValue: dataset?.data?.[index] ?? undefined, // TODO: Remove
                          }

                          const url = buildFunnelPeopleUrl(props)
                          if (url) {
                              openPersonsModal({
                                  url,
                                  title: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${dayjs(
                                      label
                                  ).format('MMMM Do YYYY')}`,
                                  aggregationTargetLabel,
                              })
                          }

                          loadPeople(props)
                      }
            }
        />
    )
}
