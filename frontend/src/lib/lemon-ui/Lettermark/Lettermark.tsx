import './Lettermark.scss'

import clsx from 'clsx'
import React from 'react'

// This is the number of known --lettermark-* variables in `globals.scss`
export const NUM_LETTERMARK_STYLES = 16

export enum LettermarkColor {
    Gray = 'gray',
}

export interface LettermarkProps {
    /** Name or value the lettermark should represent. */
    name?: string | number | null
    /** If given, will choose a color based on the index. A string is read as a UUID. */
    index?: number | string
    /** Specify the color */
    color?: LettermarkColor
    /** Circular rounded style rather than square */
    rounded?: boolean
    /** A dashed outlined style rather than filled */
    outlined?: boolean
    /** @default 'medium' */
    size?: 'xsmall' | 'small' | 'medium' | 'xlarge'
    className?: string
}

/** Picks one of the lettermark colors (1-based) for an entity ID. */
export function lettermarkColorIndex(entityId: number | string): number {
    // A whole UUID doesn't fit into the JS number type, so its last 4 bytes stand in for it.
    const index = typeof entityId === 'string' ? parseInt(entityId.split('-').at(-1)!, 16) : entityId
    return (index % NUM_LETTERMARK_STYLES) + 1
}

/** An icon-sized lettermark.
 *
 * When given a string, the initial letter is shown. Numbers up to 99 are displayed in full, in integer form.
 */
export const Lettermark = React.forwardRef<HTMLDivElement, LettermarkProps>(function Lettermark(
    { name, index, color, outlined = false, rounded = false, size = 'medium', className },
    ref
) {
    const representation = name
        ? typeof name === 'number'
            ? String(Math.floor(name))
            : String.fromCodePoint(name.codePointAt(0)!).toLocaleUpperCase()
        : '?'

    const colorIndex = color ? color : index !== undefined ? lettermarkColorIndex(index) : undefined

    return (
        <div
            className={clsx(
                `Lettermark Lettermark--${size}`,
                colorIndex && `Lettermark--variant-${colorIndex}`,
                outlined && 'Lettermark--outlined',
                rounded && 'Lettermark--rounded',
                representation === '?' && 'Lettermark--unknown',
                className
            )}
            ref={ref}
        >
            {representation}
        </div>
    )
})
