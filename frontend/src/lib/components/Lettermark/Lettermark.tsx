import clsx from 'clsx'
import React from 'react'
import './Lettermark.scss'

export enum LettermarkColor {
    Gray = 'gray',
}

export function Lettermark({ name, color }: { name?: string | number | null; color: LettermarkColor }): JSX.Element {
    const initialLetter = name ? String(name)[0].toLocaleUpperCase() : '?'

    return <div className={clsx('Lettermark', color && `Lettermark--${color}`)}>{initialLetter}</div>
}
