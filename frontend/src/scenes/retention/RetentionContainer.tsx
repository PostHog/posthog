import React from 'react'
import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionTable } from './RetentionTable'

export function RetentionContainer(props: {
    dashboardItemId?: number
    filters?: Record<string, any>
    color?: string
    inSharedMode?: boolean
}): JSX.Element {
    return (
        <div className="retention-container">
            <RetentionLineGraph {...props} />
            <RetentionTable {...props} />
        </div>
    )
}
