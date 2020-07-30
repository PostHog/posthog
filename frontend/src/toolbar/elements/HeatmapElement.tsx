import React from 'react'

interface HeatmapElementProps {
    rect?: DOMRect
    domPadding: number
    domZoom: number
    style: Record<string, any>
    onClick: (event: React.MouseEvent) => void
    onMouseOver: (event: React.MouseEvent) => void
    onMouseOut: (event: React.MouseEvent) => void
}

export function HeatmapElement({
    rect,
    domPadding,
    domZoom,
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
                top: `${(rect.top - domPadding + window.pageYOffset) / domZoom}px`,
                left: `${(rect.left - domPadding + window.pageXOffset) / domZoom}px`,
                width: `${(rect.right - rect.left) / domZoom}px`,
                height: `${(rect.bottom - rect.top) / domZoom}px`,
                ...style,
            }}
            onClick={onClick}
            onMouseOver={onMouseOver}
            onMouseOut={onMouseOut}
        />
    )
}
