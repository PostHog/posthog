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
}

export function TodaySpacesRow({ label, icon, to, active, dataAttr, action, badge }: TodaySpacesRowProps): JSX.Element {
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
                    active && 'bg-fill-selected text-foreground',
                    action && !badge && 'pr-8',
                    badge && 'pr-24'
                )}
            >
                <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
                <span className="min-w-0 flex-1 truncate">{label}</span>
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
