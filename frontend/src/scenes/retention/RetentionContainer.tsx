import React from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { useValues } from 'kea'
import { RetentionLineGraph } from './RetentionLineGraph'
import { ACTIONS_LINE_GRAPH_LINEAR } from 'lib/constants'
import { RetentionTable } from './RetentionTable'

export function RetentionContainer(props: {
    dashboardItemId: number
    filters: Record<string, any>
    color: string
    inSharedMode: boolean
}): JSX.Element {
    const logic = retentionTableLogic({ dashboardItemId: props.dashboardItemId, filters: props.filters })
    const { filters } = useValues(logic)
    return (
        <div
            style={
                filters.display === ACTIONS_LINE_GRAPH_LINEAR
                    ? {
                          minHeight: '70vh',
                          position: 'relative',
                      }
                    : {}
            }
        >
            {filters.display === ACTIONS_LINE_GRAPH_LINEAR ? (
                <RetentionLineGraph {...props} />
            ) : (
                <RetentionTable {...props} />
            )}
        </div>
    )
}
