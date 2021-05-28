import { hexToRGBA, getColorVar } from 'lib/colors'
import React from 'react'

export default function SeriesBadge({
    color,
    children,
}: {
    color: string | null
    children: React.ReactNode
}): JSX.Element {
    const backgroundColor = color ? hexToRGBA(color, 0.2) : 'none'
    const seriesColor = color || getColorVar('text_default') || 'black'
    return (
        <div
            style={{
                borderRadius: '1em',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: '2em',
                height: '2em',
                marginRight: '0.5em',
                color: seriesColor,
                backgroundColor: backgroundColor,
                boxSizing: 'border-box',
                border: `2px solid ${seriesColor}`,
            }}
        >
            {children}
        </div>
    )
}
