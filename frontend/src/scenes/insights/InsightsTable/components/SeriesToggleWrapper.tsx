import React from 'react'

interface SeriesToggleWrapperProps {
    id: number
    children: React.ReactNode | string
    toggleVisibility?: (index: number) => void
    isSingleEntity?: boolean
    style?: React.CSSProperties
}

export function SeriesToggleWrapper({
    id,
    children,
    toggleVisibility,
    isSingleEntity = false,
    style = {},
}: SeriesToggleWrapperProps): JSX.Element {
    return (
        <div
            style={{ cursor: isSingleEntity || !toggleVisibility ? undefined : 'pointer', ...style }}
            onClick={() => !isSingleEntity && toggleVisibility?.(id)}
        >
            {children}
        </div>
    )
}
