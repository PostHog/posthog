import clsx from 'clsx'
import React from 'react'
import './Lettermark.scss'

export enum LettermarkColor {
    Default = 1,
    Gray = 8,
}

export interface LettermarkProps {
    /** Name or value the lettermark should represent. */
    name?: string | number | null
    // If given, will choose a color based on the index
    index?: number
    // Specify the color
    color?: LettermarkColor
    // Specify the color
    rounded?: boolean
}

/** An icon-sized lettermark.
 *
 * When given a string, the initial letter is shown. Numbers up to 99 are displayed in full, in integer form.
 */
export function Lettermark({ name, index, color, rounded = false }: LettermarkProps): JSX.Element {
    const representation = name
        ? typeof name === 'number'
            ? String(Math.floor(name))
            : name.toLocaleUpperCase().charAt(0)
        : '?'

    const colorIndex = color ? color : typeof index === 'number' ? (index % 8) + 1 : undefined

    return (
        <div
            className={clsx(
                'Lettermark',
                colorIndex && `Lettermark--variant-${colorIndex}`,
                rounded && `Lettermark--rounded`
            )}
            title={String(name)}
        >
            {representation}
        </div>
    )
}
