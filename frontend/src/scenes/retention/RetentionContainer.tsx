import React from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { useValues } from 'kea'
import { RetentionLineGraph } from './RetentionLineGraph'
import { ACTIONS_LINE_GRAPH_LINEAR } from 'lib/constants'
import { RetentionTable } from './RetentionTable'
import { insightLogic } from 'scenes/insights/insightLogic'

export function RetentionContainer(props: {
    dashboardItemId?: number
    filters?: Record<string, any>
    color?: string
    inSharedMode?: boolean
}): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const logic = retentionTableLogic(insightProps)
    const { loadedFilters } = useValues(logic)
    return (
        <div
            style={
                !props.dashboardItemId && loadedFilters.display === ACTIONS_LINE_GRAPH_LINEAR
                    ? {
                          minHeight: '70vh',
                          position: 'relative',
                      }
                    : {
                          minHeight: '100%',
                      }
            }
        >
            {loadedFilters.display === ACTIONS_LINE_GRAPH_LINEAR ? (
                <RetentionLineGraph {...props} />
            ) : (
                <RetentionTable {...props} />
            )}
        </div>
    )
}
