import { getChartColors } from 'lib/colors'
import { alphabet, hexToRGBA } from 'lib/utils'
import React from 'react'

interface SeriesGlyphProps {
    children: React.ReactNode
    style?: React.CSSProperties
}

export function SeriesGlyph({ style, children }: SeriesGlyphProps): JSX.Element {
    return (
        <span className="graph-series-glyph" style={style}>
            {children}
        </span>
    )
}

interface SeriesLetterProps {
    hasBreakdown: boolean
    seriesIndex: number
    seriesColor?: string
}

export function SeriesLetter({ hasBreakdown, seriesIndex, seriesColor }: SeriesLetterProps): JSX.Element {
    const colorList = getChartColors('white')
    const color = seriesColor || colorList[seriesIndex % colorList.length]

    return (
        <SeriesGlyph
            style={
                !hasBreakdown
                    ? {
                          borderColor: color,
                          color: color,
                          backgroundColor: hexToRGBA(color, 0.15),
                      }
                    : undefined
            }
        >
            {alphabet[seriesIndex]}
        </SeriesGlyph>
    )
}
