import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

export interface OsDockTileProps {
    /** The tooltip, and the start of the button's accessible name. */
    label: string
    icon: JSX.Element
    open: boolean
    focused: boolean
    minimized: boolean
    onClick: (from: Element) => void
    'data-attr': string
    className?: string
}

function accessibleName(label: string, focused: boolean, minimized: boolean): string {
    if (minimized) {
        return `${label}, minimized`
    }
    return focused ? `${label}, active` : label
}

export function OsDockTile({
    label,
    icon,
    open,
    focused,
    minimized,
    onClick,
    'data-attr': dataAttr,
    className,
}: OsDockTileProps): JSX.Element {
    return (
        <li className="OsDock__item">
            <Tooltip title={label} placement="top">
                <button
                    type="button"
                    className={cn(
                        'OsDock__button',
                        focused && 'OsDock__button--focused',
                        minimized && 'OsDock__button--minimized',
                        className
                    )}
                    aria-label={accessibleName(label, focused, minimized)}
                    aria-current={focused ? 'true' : undefined}
                    onClick={(event) => onClick(event.currentTarget)}
                    data-attr={dataAttr}
                >
                    {icon}
                </button>
            </Tooltip>
            {open && <span className="OsDock__running" aria-hidden />}
        </li>
    )
}
