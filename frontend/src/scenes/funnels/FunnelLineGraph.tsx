import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { useActions, useValues } from 'kea'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { ChartParams, GraphTypes, GraphDataset } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { capitalizeFirstLetter } from 'lib/utils'

export function FunnelLineGraph({
    dashboardItemId,
    inSharedMode,
    color = 'white',
}: Omit<ChartParams, 'filters'>): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const logic = funnelLogic(insightProps)
    const { steps, filters, aggregationTargetLabel, incompletenessOffsetFromEnd } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)

    return (
        <LineGraph
            data-attr="trend-line-graph-funnel"
            type={GraphTypes.Line}
            color={color}
            datasets={steps as unknown as GraphDataset[]}
            labels={steps?.[0]?.labels ?? ([] as string[])}
            isInProgress={incompletenessOffsetFromEnd < 0}
            dashboardItemId={dashboardItemId}
            inSharedMode={!!inSharedMode}
            percentage={true}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                dashboardItemId
                    ? undefined
                    : (point) => {
                          loadPeople({
                              action: { id: point.index, name: point.label ?? null, properties: [], type: 'actions' },
                              label: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${
                                  point.label
                              }`,
                              date_from: point.day ?? '',
                              date_to: point.day ?? '',
                              filters: filters,
                              saveOriginal: true,
                              pointValue: point.value,
                          })
                      }
            }
        />
    )
}
