import React from 'react'
import { LineGraph } from 'scenes/insights/LineGraph'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { useActions, useValues } from 'kea'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { router } from 'kea-router'
import { ChartParams } from '~/types'

export function FunnelLineGraph({
    filters: defaultFilters,
    dashboardItemId,
    cachedResults,
    inSharedMode,
    color = 'white',
}: Omit<ChartParams, 'view'>): JSX.Element | null {
    const logic = funnelLogic({ dashboardItemId, cachedResults, filters: defaultFilters })
    const { steps, filters, isValidFunnel } = useValues(logic)
    const { loadPeople } = useActions(personsModalLogic)
    const {
        hashParams: { fromItem },
    } = useValues(router)

    if (!isValidFunnel) {
        return null
    }

    return (
        <LineGraph
            data-attr="trend-line-graph-funnel"
            type="line"
            color={color}
            datasets={steps}
            labels={steps[0].labels as string[]}
            isInProgress={!filters.date_to}
            dashboardItemId={dashboardItemId || fromItem}
            inSharedMode={inSharedMode}
            percentage={true}
            onClick={
                dashboardItemId
                    ? null
                    : (point) => {
                          loadPeople({
                              action: { id: point.index, name: point.label, properties: [], type: 'actions' },
                              label: `Persons converted on ${point.label}`,
                              date_from: point.day,
                              date_to: point.day,
                              filters: filters,
                              saveOriginal: true,
                          })
                      }
            }
        />
    )
}
