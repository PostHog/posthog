import { useLayoutEffect, useRef, useState } from 'react'

import { GlassIcon } from './GlassIcon'
import { IconGlyph, glyphFromSvg } from './iconGlyph'

export interface GlassIconFromElementProps {
    icon: JSX.Element
    glowColor: string
    glowColorDark: string
}

/**
 * Draws any app icon as a glass glyph. A hidden copy of the icon stays in the DOM, so its paths can
 * be read whenever the icon changes. An icon that paints more than paths stays a plain white icon.
 */
export function GlassIconFromElement({ icon, glowColor, glowColorDark }: GlassIconFromElementProps): JSX.Element {
    const sourceRef = useRef<HTMLSpanElement>(null)
    const [glyph, setGlyph] = useState<IconGlyph | null | undefined>(undefined)

    useLayoutEffect(() => {
        setGlyph(glyphFromSvg(sourceRef.current?.querySelector('svg') ?? null))
    }, [icon])

    return (
        <>
            <span ref={sourceRef} hidden>
                {icon}
            </span>
            {glyph ? (
                <GlassIcon
                    path={glyph.parts}
                    viewBox={glyph.viewBox}
                    glowColor={glowColor}
                    glowColorDark={glowColorDark}
                />
            ) : (
                <span
                    aria-hidden
                    className={
                        glyph === null
                            ? 'inline-flex size-9 items-center justify-center text-white [&_svg]:size-7'
                            : 'inline-flex size-9'
                    }
                >
                    {glyph === null && icon}
                </span>
            )}
        </>
    )
}
