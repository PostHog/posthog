import './LemonColorGlyph.scss'

import { useValues } from 'kea'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { useEffect, useState } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

type LemonColorGlyphProps = {
    color?: string | null
    className?: string
    children?: React.ReactNode
}

export function LemonColorGlyph({ color, className, children }: LemonColorGlyphProps): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const [lastValidColor, setLastValidColor] = useState<string>('#000000')

    const isUnset = color == null

    useEffect(() => {
        // allow only 6-digit hex colors
        // other color formats are not supported everywhere e.g. insight visualizations
        if (!isUnset && /^#[0-9A-Fa-f]{6}$/.test(color)) {
            setLastValidColor(color)
        }
    }, [color, isUnset])

    return (
        <div
            className={cn('LemonColorGlyph', { 'LemonColorGlyph--unset': isUnset }, className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                !isUnset
                    ? {
                          borderColor: lastValidColor,
                          color: lastValidColor,
                          backgroundColor: isDarkModeOn
                              ? RGBToRGBA(lightenDarkenColor(lastValidColor, -20), 0.3)
                              : hexToRGBA(lastValidColor, 0.2),
                      }
                    : undefined
            }
        >
            {isUnset && <div className="LemonColorGlyph__strikethrough" />}
            {children}
        </div>
    )
}
