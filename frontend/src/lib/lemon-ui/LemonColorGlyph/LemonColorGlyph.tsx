import './LemonColorGlyph.scss'

import { useValues } from 'kea'
import { DataColorToken } from 'lib/colors'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

export type LemonColorGlyphProps = {
    /** Overwrite the theme id from the context e.g. an insight that has a custom theme set. */
    themeId?: string | null
    /** Additional class names. */
    className?: string
    /** Content to display inside the glyph. */
    children?: React.ReactNode
    /** 6-digit hex color to display. */
    color?: string | null
    /** Color token to display. Takes precedence over `color`. */
    colorToken?: DataColorToken | null
}

/** Takes a 6-digit hex color or a color token and displays it as a glyph. */
export function LemonColorGlyph({
    color,
    colorToken,
    themeId,
    className,
    children,
}: LemonColorGlyphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { getTheme } = useValues(dataThemeLogic)

    const theme = getTheme(themeId)

    // display a placeholder while loading the theme
    if (colorToken != null && theme == null) {
        return <div className={cn('LemonColorGlyph LemonColorGlyph--placeholder', className)}>{children}</div>
    }

    const appliedColor = colorToken ? (theme?.[colorToken] as string) : color

    // display a glyph for an unset color
    if (appliedColor == null) {
        return (
            <div className={cn('LemonColorGlyph LemonColorGlyph--unset', className)}>
                <div className="LemonColorGlyph__strikethrough" />
                {children}
            </div>
        )
    }

    // display a glyph for the given color/token
    return (
        <div
            className={cn('LemonColorGlyph', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: appliedColor,
                color: appliedColor,
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor(appliedColor, -20), 0.3)
                    : hexToRGBA(appliedColor, 0.2),
            }}
        >
            {children}
        </div>
    )
}
