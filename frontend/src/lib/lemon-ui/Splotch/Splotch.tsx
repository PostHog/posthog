import clsx from 'clsx'

// Keep this enum in sync with InsightColor values used for dashboard tile colors.
export enum SplotchColor {
    Purple = 'purple',
    Blue = 'blue',
    Green = 'green',
    Black = 'black',
    White = 'white',
    Red = 'red',
    Orange = 'orange',
    Teal = 'teal',
    Cyan = 'cyan',
    Pink = 'pink',
}

export interface SplotchProps {
    color: SplotchColor
}

function colorClassForSplotch(color: SplotchColor): string {
    switch (color) {
        case SplotchColor.Blue:
            return 'bg-[var(--blue)]'
        case SplotchColor.Purple:
            return 'bg-[var(--purple)]'
        case SplotchColor.Green:
            return 'bg-[var(--green)]'
        case SplotchColor.Black:
            return 'bg-[var(--black)]'
        case SplotchColor.Red:
            return 'bg-[var(--danger)]'
        case SplotchColor.Orange:
            return 'bg-[var(--warning)]'
        case SplotchColor.Teal:
            return 'bg-[var(--data-color-3)]'
        case SplotchColor.Cyan:
            return 'bg-[var(--data-color-11)]'
        case SplotchColor.Pink:
            return 'bg-[var(--data-color-9)]'
        case SplotchColor.White:
            return 'bg-white border border-[var(--color-border-primary)]'
        default:
            return ''
    }
}

/** An icon-sized blob signifying the given color. It can serve e.g. as a `LemonButton` icon in a color selection menu. */
export function Splotch({ color }: SplotchProps): JSX.Element {
    return (
        <div className="size-6 items-center justify-center p-1" data-attr="splotch-icon">
            <div className={clsx('size-4 rounded', colorClassForSplotch(color))} data-attr="splotch-icon-paint" />
        </div>
    )
}
