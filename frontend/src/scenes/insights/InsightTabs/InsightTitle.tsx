import React from 'react'

export function InsightTitle({ actionBar = null }: { actionBar?: JSX.Element | null }): JSX.Element {
    return (
        <>
            <h3 className="l3 insight-title-container">{actionBar}</h3>
        </>
    )
}
