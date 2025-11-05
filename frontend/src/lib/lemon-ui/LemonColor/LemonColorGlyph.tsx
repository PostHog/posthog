import './LemonColorGlyph.scss'

import { useValues } from 'kea'

import { DataColorToken } from 'lib/colors'
import { RGBToRGBA, hexToRGBA, lightenDarkenColor } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { LemonButtonWithoutSideActionProps } from '../LemonButton'

type LemonColorGlyphBaseProps = {
    /** Additional class names. */
    className?: string
    /** Content to display inside the glyph. */
    children?: React.ReactNode
} & Pick<LemonButtonWithoutSideActionProps, 'size'>

type LemonColorGlyphColorProps = LemonColorGlyphBaseProps & {
    /** 6-digit hex color to display. */
    color?: string | null
    colorToken?: never
    themeId?: never
}

type LemonColorGlyphTokenProps = LemonColorGlyphBaseProps & {
    /** Color token to display. */
    colorToken?: DataColorToken | null
    /** Overwrite the theme id from the context e.g. an insight that has a custom theme set. */
    themeId?: number | null
    color?: never
}

export type LemonColorGlyphProps = LemonColorGlyphColorProps | LemonColorGlyphTokenProps

/** Takes a 6-digit hex color or a color token and displays it as a glyph. */
export function LemonColorGlyph({
    color,
    colorToken,
    themeId,
    size,
    className,
    children,
}: LemonColorGlyphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const { getTheme, getColorFromToken } = useValues(dataThemeLogic)

    const theme = getTheme(themeId)

    // display a placeholder while loading the theme
    if (colorToken != null && theme == null) {
        return (
            <div
                className={cn(
                    'LemonColorGlyph LemonColorGlyph--placeholder',
                    { 'LemonColorGlyph--small': size === 'small' },
                    className
                )}
            >
                {children}
            </div>
        )
    }

    const effectiveColor = colorToken ? getColorFromToken(themeId, colorToken) : color

    // display a glyph for an unset color
    if (effectiveColor == null) {
        return (
            <div
                className={cn(
                    'LemonColorGlyph LemonColorGlyph--unset',
                    { 'LemonColorGlyph--small': size === 'small' },
                    className
                )}
            >
                <div className="LemonColorGlyph__strikethrough" />
                {children}
            </div>
        )
    }

    // display a glyph for the given color/token
    return (
        <div
            className={cn('LemonColorGlyph', { 'LemonColorGlyph--small': size === 'small' }, className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: effectiveColor,
                color: effectiveColor,
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor(effectiveColor, -20), 0.3)
                    : hexToRGBA(effectiveColor, 0.2),
            }}
        >
            {children}
        </div>
    )
}
