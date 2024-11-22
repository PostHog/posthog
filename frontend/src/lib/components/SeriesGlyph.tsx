import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { alphabet, hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { useEffect, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

interface SeriesGlyphProps {
    className?: string
    children?: React.ReactNode
    style?: React.CSSProperties
    variant?: 'funnel-step-glyph' // Built-in styling defaults
}

export function SeriesGlyph({ className, style, children, variant }: SeriesGlyphProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className={`graph-series-glyph ${variant || ''} ${className}`} style={style}>
            {children}
        </div>
    )
}

type ColorGlyphProps = {
    color?: string | null
} & SeriesGlyphProps

export function ColorGlyph({ color, ...rest }: ColorGlyphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    const [lastValidColor, setLastValidColor] = useState<string>('#000000')

    useEffect(() => {
        // allow only 6-digit hex colors
        // other color formats are not supported everywhere e.g. insight visualizations
        if (color != null && /^#[0-9A-Fa-f]{6}$/.test(color)) {
            setLastValidColor(color)
        }
    }, [color])

    return (
        <SeriesGlyph
            style={{
                borderColor: lastValidColor,
                color: lastValidColor,
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor(lastValidColor, -20), 0.3)
                    : hexToRGBA(lastValidColor, 0.2),
            }}
            {...rest}
        />
    )
}

interface SeriesLetterProps {
    className?: string
    hasBreakdown: boolean
    seriesIndex: number
    seriesColor?: string
}

export function SeriesLetter({ className, hasBreakdown, seriesIndex, seriesColor }: SeriesLetterProps): JSX.Element {
    const color = seriesColor || getSeriesColor(seriesIndex)
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <SeriesGlyph
            className={className}
            style={
                !hasBreakdown
                    ? {
                          borderColor: color,
                          color: color,
                          backgroundColor: isDarkModeOn
                              ? RGBToRGBA(lightenDarkenColor(color, -20), 0.3)
                              : hexToRGBA(color, 0.2),
                      }
                    : {
                          color: 'var(--text-3000)',
                      }
            }
        >
            {alphabet[seriesIndex]}
        </SeriesGlyph>
    )
}

interface ExperimentVariantNumberProps {
    className?: string
    index: number
}
export function ExperimentVariantNumber({ className, index }: ExperimentVariantNumberProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    return (
        <SeriesGlyph
            className={className}
            style={{
                borderColor: 'var(--muted)',
                color: 'var(--muted)',
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor('var(--muted)', -20), 0.3)
                    : hexToRGBA('var(--muted)', 0.2),
            }}
        >
            {index}
        </SeriesGlyph>
    )
}
