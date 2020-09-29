import React from 'react'

interface HeatmapElementProps {
    rect?: DOMRect
    style: Record<string, any>
    onClick: (event: React.MouseEvent) => void
    onMouseOver: (event: React.MouseEvent) => void
    onMouseOut: (event: React.MouseEvent) => void
}

export function HeatmapElement({
    rect,
    style = {},
    onClick,
    onMouseOver,
    onMouseOut,
}: HeatmapElementProps): JSX.Element | null {
    if (!rect) {
        return null
    }
    return (
        <div
            style={{
                position: 'absolute',
                top: `${rect.top + window.pageYOffset}px`,
                left: `${rect.left + window.pageXOffset}px`,
                width: `${rect.right - rect.left}px`,
                height: `${rect.bottom - rect.top}px`,
                ...style,
            }}
            onClick={onClick}
            onMouseOver={onMouseOver}
            onMouseOut={onMouseOut}
        />
    )
}
