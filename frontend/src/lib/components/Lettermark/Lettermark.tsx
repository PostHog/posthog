import clsx from 'clsx'
import React from 'react'
import './Lettermark.scss'

export enum LettermarkColor {
    Gray = 'gray',
}

export interface LettermarkProps {
    /** Name or value the lettermark should represent. */
    name?: string | number | null
    color?: LettermarkColor
}

/** An icon-sized lettermark.
 *
 * When given a string, the initial letter is shown. Numbers up to 99 are displayed in full, in integer form.
 */
export function Lettermark({ name, color }: LettermarkProps): JSX.Element {
    const representation = name
        ? typeof name === 'number'
            ? String(Math.floor(name))
            : name.toLocaleUpperCase().charAt(0)
        : '?'

    return (
        <div className={clsx('Lettermark', color && `Lettermark--${color}`)} title={String(name)}>
            {representation}
        </div>
    )
}
