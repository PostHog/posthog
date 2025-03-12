import './Splotch.scss'

import { cn } from 'lib/utils/css-classes'

export enum SplotchColor {
    Purple = 'purple',
    Blue = 'blue',
    Green = 'green',
    Black = 'black',
    White = 'white',
}

export interface SplotchProps {
    color: SplotchColor
}

/** An icon-sized blob signifying the given color. It can serve e.g. as a `LemonButton` icon in a color selection menu. */
export function Splotch({ color }: SplotchProps): JSX.Element {
    return (
        <div className={cn('Splotch', `Splotch--${color}`)}>
            <div className="Splotch__paint" />
        </div>
    )
}
