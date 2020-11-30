import React from 'react'
import { retentionTableLogic } from './retentionTableLogic'
import { useValues } from 'kea'
import { RetentionLineGraph } from './RetentionLineGraph'
import { ACTIONS_LINE_GRAPH_LINEAR } from 'lib/constants'
import { RetentionTable } from './RetentionTable'

export function RetentionContainer(): JSX.Element {
    const { filters } = useValues(retentionTableLogic({ dashboardItemId: null }))
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
            {filters.display === ACTIONS_LINE_GRAPH_LINEAR ? <RetentionLineGraph /> : <RetentionTable />}
        </div>
    )
}
