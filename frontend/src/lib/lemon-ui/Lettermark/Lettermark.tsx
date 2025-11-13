import './Lettermark.scss'

import clsx from 'clsx'
import React from 'react'

// This is the number of known --lettermark-* variables in `globals.scss`
const NUM_LETTERMARK_STYLES = 8

export enum LettermarkColor {
    Gray = 'gray',
}

export interface LettermarkProps {
    /** Name or value the lettermark should represent. */
    name?: string | number | null
    /** If given, will choose a color based on the index */
    index?: number
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

    const colorIndex = color ? color : typeof index === 'number' ? (index % NUM_LETTERMARK_STYLES) + 1 : undefined

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
