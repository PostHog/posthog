import { Fragment, useId } from 'react'

import { cn } from 'lib/utils/css-classes'

/** One sub-shape of a glyph. A glyph made of overlapping segments passes several. */
export interface GlyphPart {
    d: string
    fillRule?: 'nonzero' | 'evenodd'
}

export interface GlassIconProps {
    /** One fill path, or the parts of a glyph drawn from several shapes. */
    path: string | GlyphPart[]
    /** Defaults to the 36-unit canvas the posthog.com glyphs use. */
    viewBox?: string
    /** Fill rule for a single `path` string; `evenodd` keeps cut-outs as holes. */
    fillRule?: 'nonzero' | 'evenodd'
    /** Hover glow in light mode. */
    glowColor: string
    /** Hover glow in dark mode. */
    glowColorDark: string
    className?: string
}

// Stroke and shadow sizes are tuned for the 36-unit canvas, and scale with any other viewBox.
const DESIGN_CANVAS = 36
const FILL_OPACITY = 0.5
const FROST_BLUR_PX = 1.3

/**
 * A frosted-glass desktop icon, ported from posthog.com. Two stacked copies of the glyph give the look:
 * a translucent fill with a soft outer edge and a drop shadow, and a bright inner highlight on top.
 * The hover effects need a `group` class on an ancestor.
 */
export function GlassIcon({
    path,
    viewBox = `0 0 ${DESIGN_CANVAS} ${DESIGN_CANVAS}`,
    fillRule = 'nonzero',
    glowColor,
    glowColorDark,
    className,
}: GlassIconProps): JSX.Element {
    const id = useId().replace(/:/g, '')
    const frostClipId = `${id}-frost`
    const shadowId = `${id}-shadow`

    const parts: GlyphPart[] = typeof path === 'string' ? [{ d: path, fillRule }] : path

    const [vbX, vbY, vbW, vbH] = viewBox.split(/\s+/).map(Number)
    const longestSide = Math.max(vbW, vbH)
    const unit = longestSide / DESIGN_CANVAS
    // Doubled, because each mask keeps one half of the stroke.
    const strokeWidth = 1 * unit
    const shadowOffset = 1 * unit
    const maskX = vbX - 2 * unit
    const maskY = vbY - 2 * unit
    const maskW = vbW + 4 * unit
    const maskH = vbH + 4 * unit

    return (
        <span className={cn('relative inline-flex items-center justify-center size-9', className)}>
            <span
                aria-hidden
                className="pointer-events-none absolute inset-1 rounded-[40%] blur-md opacity-0 transition-opacity duration-700 ease-out group-hover:opacity-60 dark:group-hover:opacity-0 motion-reduce:transition-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: glowColor }}
            />
            <span
                aria-hidden
                className="pointer-events-none absolute inset-1 rounded-[40%] blur-md opacity-0 transition-opacity duration-700 ease-out dark:group-hover:opacity-60 motion-reduce:transition-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ backgroundColor: glowColorDark }}
            />
            {/* The backdrop blur is costly, so it only renders while the icon is hovered. */}
            <span
                aria-hidden
                className="pointer-events-none absolute inset-0 hidden group-hover:block scale-[1.03]"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backdropFilter: `blur(${FROST_BLUR_PX}px)`,
                    WebkitBackdropFilter: `blur(${FROST_BLUR_PX}px)`,
                    clipPath: `url(#${frostClipId})`,
                }}
            />
            <svg
                aria-hidden
                viewBox={viewBox}
                fill="none"
                className="relative block size-full overflow-visible transition-transform duration-200 ease-out group-hover:scale-[1.03] motion-reduce:transition-none"
            >
                <defs>
                    {/* Maps the glyph into the frost's box the same way the SVG's "meet" scaling does. */}
                    <clipPath id={frostClipId} clipPathUnits="objectBoundingBox">
                        {parts.map((part, index) => (
                            <path
                                key={index}
                                d={part.d}
                                fillRule={part.fillRule}
                                transform={`translate(${0.5 - (vbX + vbW / 2) / longestSide} ${
                                    0.5 - (vbY + vbH / 2) / longestSide
                                }) scale(${1 / longestSide})`}
                            />
                        ))}
                    </clipPath>
                    {parts.map((part, index) => (
                        <Fragment key={index}>
                            <mask
                                id={`${id}-outer${index}`}
                                maskUnits="userSpaceOnUse"
                                x={maskX}
                                y={maskY}
                                width={maskW}
                                height={maskH}
                            >
                                <rect x={maskX} y={maskY} width={maskW} height={maskH} fill="white" />
                                <path d={part.d} fill="black" fillRule={part.fillRule} />
                            </mask>
                            <mask
                                id={`${id}-inner${index}`}
                                maskUnits="userSpaceOnUse"
                                x={maskX}
                                y={maskY}
                                width={maskW}
                                height={maskH}
                            >
                                <path d={part.d} fill="white" fillRule={part.fillRule} />
                            </mask>
                        </Fragment>
                    ))}
                    {/* The "out" composite removes each shadow from behind the shape, so it does not
                        darken the translucent fill. */}
                    <filter id={shadowId} x="-50%" y="-50%" width="200%" height="200%" colorInterpolationFilters="sRGB">
                        <feFlood floodOpacity="0" result="BackgroundImageFix" />
                        <feColorMatrix
                            in="SourceAlpha"
                            type="matrix"
                            values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                            result="hardAlpha"
                        />
                        <feOffset dy={shadowOffset} />
                        <feGaussianBlur stdDeviation={1 * unit} />
                        <feComposite in2="hardAlpha" operator="out" />
                        <feColorMatrix
                            type="matrix"
                            values="0 0 0 0 0.0117647 0 0 0 0 0.188235 0 0 0 0 0.0117647 0 0 0 1 0"
                        />
                        <feBlend mode="normal" in2="BackgroundImageFix" result="shadow1" />
                        <feColorMatrix
                            in="SourceAlpha"
                            type="matrix"
                            values="0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 127 0"
                            result="hardAlpha"
                        />
                        <feOffset dy={shadowOffset} />
                        <feGaussianBlur stdDeviation={0.5 * unit} />
                        <feComposite in2="hardAlpha" operator="out" />
                        <feColorMatrix
                            type="matrix"
                            values="0 0 0 0 0.0117647 0 0 0 0 0.188235 0 0 0 0 0.0117647 0 0 0 0.25 0"
                        />
                        <feBlend mode="normal" in2="shadow1" result="shadow2" />
                        <feBlend mode="normal" in="SourceGraphic" in2="shadow2" result="shape" />
                    </filter>
                </defs>
                <g filter={`url(#${shadowId})`}>
                    <g opacity={FILL_OPACITY}>
                        {parts.map((part, index) => (
                            <path key={index} d={part.d} fill="white" fillRule={part.fillRule} />
                        ))}
                    </g>
                    {parts.map((part, index) => (
                        <path
                            key={index}
                            d={part.d}
                            fill="none"
                            stroke="white"
                            strokeOpacity={0.55}
                            strokeWidth={strokeWidth}
                            mask={`url(#${id}-outer${index})`}
                        />
                    ))}
                </g>
                <g>
                    {parts.map((part, index) => (
                        <path
                            key={index}
                            d={part.d}
                            fill="none"
                            stroke="white"
                            strokeWidth={strokeWidth}
                            mask={`url(#${id}-inner${index})`}
                        />
                    ))}
                </g>
            </svg>
        </span>
    )
}
