import React from 'react'
import { inBounds } from '~/toolbar/utils'

const heatmapLabelStyle = {
    lineHeight: '14px',
    padding: '1px 4px',
    color: 'hsla(54, 20%, 12%, 1)',
    background: '#FFEB3B',
    boxShadow: 'hsla(54, 100%, 32%, 1) 0px 1px 5px 1px',
    fontSize: 16,
    fontWeight: 'bold' as const,
    fontFamily: 'monospace',
}

interface HeatmapLabelProps extends React.PropsWithoutRef<JSX.IntrinsicElements['div']> {
    rect?: DOMRect
    domPadding: number
    domZoom: number
    align?: 'left' | 'right'
}

export function HeatmapLabel({
    rect,
    domPadding,
    domZoom,
    style = {},
    align = 'right',
    children,
    ...props
}: HeatmapLabelProps): JSX.Element | null {
    if (!rect) {
        return null
    }
    return (
        <div
            style={{
                position: 'absolute',
                top: `${
                    inBounds(
                        window.pageYOffset - 1 - domPadding,
                        rect.top - domPadding - 7 + window.pageYOffset,
                        window.pageYOffset + window.innerHeight - 14
                    ) / domZoom
                }px`,
                left: `${
                    inBounds(
                        window.pageXOffset,
                        rect.left + (align === 'left' ? 10 : rect.width) - domPadding - 14 + window.pageXOffset,
                        window.pageXOffset + window.innerWidth - 14
                    ) / domZoom
                }px`,
                ...heatmapLabelStyle,
                ...style,
            }}
            {...props}
        >
            {children}
        </div>
    )
}
