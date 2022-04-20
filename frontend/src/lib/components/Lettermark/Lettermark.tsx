import clsx from 'clsx'
import React from 'react'
import './Lettermark.scss'

export enum LettermarkColor {
    Gray = 'gray',
}

export interface LettermarkProps {
    name?: string | number | null
    color?: LettermarkColor
    /** Whether (up to) two letters should be shown instead of one. */
    double?: boolean
}

export function Lettermark({ name, color, double }: LettermarkProps): JSX.Element {
    const initialLetter = name
        ? String(name)
              .slice(0, double ? 2 : 1)
              .toLocaleUpperCase()
        : '?'

    return <div className={clsx('Lettermark', color && `Lettermark--${color}`)}>{initialLetter}</div>
}
