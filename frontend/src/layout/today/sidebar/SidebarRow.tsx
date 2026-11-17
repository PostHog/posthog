import './sidebar.scss'

import { cn } from '@posthog/quill'

import { SidebarOption } from './SidebarOption'

interface SidebarRowProps {
    value: string
    label: string
    meta?: string
    icon?: JSX.Element | null
    to: string
    active?: boolean
    variant?: 'default' | 'destructive'
    /** A control that sits on the row's right edge and shows on hover, outside the row's own link. */
    action?: JSX.Element | null
    /** Keeps the action shown without a hover, for a state the row must always show, like a star. */
    actionVisible?: boolean
    dataAttr?: string
    onClick?: () => void
}

export function SidebarRow({
    value,
    label,
    meta,
    icon,
    to,
    active = false,
    variant,
    action,
    actionVisible = false,
    dataAttr,
    onClick,
}: SidebarRowProps): JSX.Element {
    return (
        <div className="group/row relative flex min-w-0 items-center">
            <SidebarOption
                value={value}
                to={to}
                active={active}
                variant={variant}
                title={label}
                data-attr={dataAttr}
                // Capture-phase, so Cmd/Ctrl-clicks count too: the link's own handler returns
                // for those before it calls onClick. Middle-clicks only fire auxclick.
                onClickCapture={onClick}
                onAuxClick={(event) => event.button === 1 && onClick?.()}
                className={cn(action && 'pr-8')}
            >
                {icon && (
                    <span
                        className="TodayIconBadge flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
                        data-keep-color
                        aria-hidden
                    >
                        {icon}
                    </span>
                )}
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {meta && (
                    <span
                        className={cn(
                            'shrink-0 text-xs font-normal text-muted-foreground',
                            // The hover action takes the meta's place at the end of the row.
                            action && 'group-hover/row:invisible group-focus-within/row:invisible'
                        )}
                    >
                        {meta}
                    </span>
                )}
            </SidebarOption>
            {action && (
                <span
                    className={cn(
                        'absolute right-1 flex items-center transition-opacity',
                        !actionVisible && 'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100'
                    )}
                >
                    {action}
                </span>
            )}
        </div>
    )
}
