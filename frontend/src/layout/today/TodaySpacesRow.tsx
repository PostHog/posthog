import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface TodaySpacesRowProps {
    label: string
    icon: JSX.Element
    to: string
    active: boolean
    dataAttr: string
    action?: JSX.Element | null
}

export function TodaySpacesRow({ label, icon, to, active, dataAttr, action }: TodaySpacesRowProps): JSX.Element {
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
                    action && 'pr-8'
                )}
            >
                <span className="flex size-4 shrink-0 items-center justify-center">{icon}</span>
                <span className="min-w-0 flex-1 truncate">{label}</span>
            </Button>
            {action && (
                <div
                    data-not-quill
                    className="absolute right-1 flex opacity-0 transition-opacity group-focus-within/row:opacity-100 group-hover/row:opacity-100"
                >
                    {action}
                </div>
            )}
        </div>
    )
}
