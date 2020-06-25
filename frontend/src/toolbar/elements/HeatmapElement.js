import React from 'react'

export function HeatmapElement({ rect, domPadding, domZoom, style = {}, onClick, onMouseOver, onMouseOut }) {
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
