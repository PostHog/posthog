import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { useActions, useValues } from 'kea'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { ChartParams, GraphType, GraphDataset } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { dayjs } from 'lib/dayjs'

export function FunnelLineGraph({
    dashboardItemId,
    inSharedMode,
    color = 'white',
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps, insight } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { steps, filters, aggregationTargetLabel, incompletenessOffsetFromEnd } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)

    return (
        <LineGraph
            data-attr="trend-line-graph-funnel"
            type={GraphType.Line}
            color={color}
            datasets={steps as unknown as GraphDataset[] /* TODO: better typing */}
            labels={steps?.[0]?.labels ?? ([] as string[])}
            isInProgress={incompletenessOffsetFromEnd < 0}
            insightId={insight.id}
            inSharedMode={!!inSharedMode}
            percentage={true}
            labelGroupType={filters.aggregation_group_type_index ?? 'people'}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                dashboardItemId
                    ? undefined
                    : (payload) => {
                          const { points, index } = payload
                          const dataset = points.clickedPointNotLine
                              ? points.pointsIntersectingClick[0].dataset
                              : points.pointsIntersectingLine[0].dataset
                          const day = dataset?.days?.[index] ?? ''
                          const label = dataset?.label ?? dataset?.labels?.[index] ?? ''

                          loadPeople({
                              action: { id: index, name: label ?? null, properties: [], type: 'actions' },
                              label: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${dayjs(
                                  label
                              ).format('MMMM Do YYYY')}`,
                              date_from: day ?? '',
                              date_to: day ?? '',
                              filters: filters,
                              saveOriginal: true,
                              pointValue: dataset?.data?.[index] ?? undefined,
                          })
                      }
            }
        />
    )
}
