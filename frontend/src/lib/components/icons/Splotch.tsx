import clsx from 'clsx'
import React from 'react'
import './Splotch.scss'

export enum SplotchColor {
    Purple = 'purple',
    Blue = 'blue',
    Green = 'green',
    Black = 'black',
    White = 'white',
}

/**
 * An "icon" that signifies the specified color with a sort of blob of that color.
 * This can fit everywhere a standard icon would – e.g. as a button icon in a menu for color selection.
 */
export function Splotch({ color }: { color: SplotchColor }): JSX.Element {
    return (
        <div className="Splotch">
            <div className={clsx('paint', color)} />
        </div>
    )
}
