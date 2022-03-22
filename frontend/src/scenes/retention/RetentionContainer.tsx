import React from 'react'
import { RetentionLineGraph } from './RetentionLineGraph'
import { RetentionTable } from './RetentionTable'

export function RetentionContainer({
    inCardView,
    inSharedMode,
}: {
    inCardView?: boolean
    inSharedMode?: boolean
}): JSX.Element {
    return (
        <div className="retention-container">
            {!inCardView && <RetentionLineGraph inCardView={inCardView} inSharedMode={inSharedMode} />}
            <RetentionTable inCardView={inCardView} />
        </div>
    )
}
