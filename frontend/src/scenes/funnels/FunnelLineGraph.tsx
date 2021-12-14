import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { useActions, useValues } from 'kea'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { ChartParams } from '~/types'
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
            type="line"
            color={color}
            datasets={steps}
            labels={steps?.[0]?.labels ?? ([] as string[])}
            isInProgress={incompletenessOffsetFromEnd < 0}
            dashboardItemId={dashboardItemId}
            inSharedMode={inSharedMode}
            percentage={true}
            incompletenessOffsetFromEnd={incompletenessOffsetFromEnd}
            onClick={
                dashboardItemId
                    ? null
                    : (point) => {
                          loadPeople({
                              action: { id: point.index, name: point.label, properties: [], type: 'actions' },
                              label: `${capitalizeFirstLetter(aggregationTargetLabel.plural)} converted on ${
                                  point.label
                              }`,
                              date_from: point.day,
                              date_to: point.day,
                              filters: filters,
                              saveOriginal: true,
                              pointValue: point.value,
                          })
                      }
            }
        />
    )
}
