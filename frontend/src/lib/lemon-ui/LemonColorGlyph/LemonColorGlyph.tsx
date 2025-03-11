import { useValues } from 'kea'
import { hexToRGBA, lightenDarkenColor, RGBToRGBA } from 'lib/utils'
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

    useEffect(() => {
        // allow only 6-digit hex colors
        // other color formats are not supported everywhere e.g. insight visualizations
        if (color != null && /^#[0-9A-Fa-f]{6}$/.test(color)) {
            setLastValidColor(color)
        }
    }, [color])

    return (
        <div
            className={`graph-series-glyph ${className}`}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                borderColor: lastValidColor,
                color: lastValidColor,
                backgroundColor: isDarkModeOn
                    ? RGBToRGBA(lightenDarkenColor(lastValidColor, -20), 0.3)
                    : hexToRGBA(lastValidColor, 0.2),
            }}
        >
            {children}
        </div>
    )
}
