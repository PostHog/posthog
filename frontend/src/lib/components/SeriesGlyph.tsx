import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { alphabet, hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'

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
                          color: 'var(--color-foreground)',
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
                borderColor: 'var(--color-secondary-foreground)',
                color: 'var(--color-secondary-foreground)',
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor('var(--color-secondary-foreground)', -20), 0.3)
                    : hexToRGBA('var(--color-secondary-foreground)', 0.2),
            }}
        >
            {index}
        </SeriesGlyph>
    )
}
