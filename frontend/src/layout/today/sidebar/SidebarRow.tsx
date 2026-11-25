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

export function SidebarRowIcon({ icon }: { icon: JSX.Element }): JSX.Element {
    return (
        <span
            className="TodayIconBadge flex size-4 shrink-0 items-center justify-center [&_svg]:size-4"
            data-keep-color
            aria-hidden
        >
            {icon}
        </span>
    )
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
        <div
            className={cn(
                'SidebarRow group/row relative flex min-w-0 items-center',
                action && 'SidebarRow--hasAction',
                actionVisible && 'SidebarRow--actionVisible'
            )}
        >
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
                className="SidebarRow__option"
            >
                {icon && <SidebarRowIcon icon={icon} />}
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {meta && (
                    <span className="SidebarRow__meta shrink-0 text-xs font-normal text-muted-foreground">{meta}</span>
                )}
            </SidebarOption>
            {action && <span className="SidebarRow__action absolute right-1 flex items-center">{action}</span>}
        </div>
    )
}
