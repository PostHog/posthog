import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface TodaySpacesRowProps {
    label: string
    icon: JSX.Element
    to: string
    active: boolean
    dataAttr: string
    action?: JSX.Element | null
    /** Stays visible at the end of the row, after the hover action. */
    badge?: JSX.Element | null
    /** How many icon buttons `action` holds, so the label truncates before them. */
    actionCount?: 1 | 2
    unread?: boolean
}

export function TodaySpacesRow({
    label,
    icon,
    to,
    active,
    dataAttr,
    action,
    badge,
    actionCount = 1,
    unread = false,
}: TodaySpacesRowProps): JSX.Element {
    return (
        <div className="group/row relative flex min-w-0 items-center">
            <Button
                size="row"
                left
                render={<LinkPrimitive to={to} />}
                aria-current={active ? 'page' : undefined}
                data-attr={dataAttr}
                className={cn(
                    'min-w-0 text-muted-foreground',
                    (active || unread) && 'text-foreground',
                    active && 'bg-fill-selected',
                    action && !badge && (actionCount === 2 ? 'pr-12' : 'pr-8'),
                    badge && 'pr-24'
                )}
            >
                <span className="flex size-3.5 shrink-0 items-center justify-center">{icon}</span>
                <span className={cn('min-w-0 flex-1 truncate', unread && 'font-semibold')}>{label}</span>
                {unread && !active && (
                    <span
                        role="img"
                        aria-label="Unread"
                        className="size-1.5 shrink-0 rounded-full bg-primary"
                        data-attr="today-unread-dot"
                    />
                )}
            </Button>
            {(action || badge) && (
                <div className="absolute right-1 flex min-w-0 items-center gap-0.5">
                    {action && (
                        <div className="flex opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100">
                            {action}
                        </div>
                    )}
                    {badge}
                </div>
            )}
        </div>
    )
}
