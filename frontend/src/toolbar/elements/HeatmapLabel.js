import React from 'react'
import { inBounds } from '~/toolbar/elements/utils'

export function HeatmapLabel({ rect, domPadding, domZoom, style = {}, children }) {
    return (
        <div
            style={{
                position: 'absolute',
                top: `${inBounds(
                    window.pageYOffset,
                    rect.top - domPadding - 7 + window.pageYOffset,
                    window.pageYOffset + window.innerHeight - 14
                ) / domZoom}px`,
                left: `${inBounds(
                    window.pageXOffset,
                    rect.left + rect.width - domPadding - 14 + window.pageXOffset,
                    window.pageXOffset + window.innerWidth - 14
                ) / domZoom}px`,
                lineHeight: '14px',
                padding: '1px 4px',
                color: 'hsla(54, 20%, 12%, 1)',
                background: '#FFEB3B',
                boxShadow: 'hsla(54, 100%, 32%, 1) 0px 1px 5px 1px',
                fontSize: 16,
                fontWeight: 'bold',
                fontFamily: 'monospace',
                ...style,
            }}
        >
            {children}
        </div>
    )
}
