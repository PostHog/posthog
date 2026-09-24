import { useLayoutEffect, useRef, useState } from 'react'

import { cn } from 'lib/utils/css-classes'

import { GlassIcon } from './GlassIcon'
import { IconGlyph, glyphFromSvg } from './iconGlyph'

export interface GlassIconFromElementProps {
    icon: JSX.Element
    glowColor: string
    glowColorDark: string
    highlighted?: boolean
}

/**
 * Draws any app icon as a glass glyph. A hidden copy of the icon stays in the DOM, so its paths can
 * be read whenever the icon changes. An icon that paints more than paths stays a plain white icon.
 */
export function GlassIconFromElement({
    icon,
    glowColor,
    glowColorDark,
    highlighted,
}: GlassIconFromElementProps): JSX.Element {
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
                    highlighted={highlighted}
                />
            ) : (
                <span
                    aria-hidden
                    className={
                        glyph === null
                            ? cn(
                                  'inline-flex size-9 items-center justify-center [&_svg]:size-7',
                                  highlighted ? 'text-accent' : 'text-white'
                              )
                            : 'inline-flex size-9'
                    }
                >
                    {glyph === null && icon}
                </span>
            )}
        </>
    )
}
