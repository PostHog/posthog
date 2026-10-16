import { cn } from '@posthog/quill'

import { TodayPaneOption } from './TodayPaneOption'

interface TodayPaneRowProps {
    value: string
    label: string
    meta?: string
    icon?: JSX.Element | null
    /** A small status mark after the label, such as a release stage. */
    badge?: JSX.Element | null
    to: string
    active?: boolean
    variant?: 'default' | 'destructive'
    /** A control that sits on the row's right edge and shows on hover, outside the row's own link. */
    action?: JSX.Element | null
    dataAttr?: string
    onClick?: () => void
}

export function TodayPaneRow({
    value,
    label,
    meta,
    icon,
    badge,
    to,
    active = false,
    variant,
    action,
    dataAttr,
    onClick,
}: TodayPaneRowProps): JSX.Element {
    return (
        <div className="group/row relative flex min-w-0 items-center">
            <TodayPaneOption
                value={value}
                to={to}
                active={active}
                variant={variant}
                title={label}
                data-attr={dataAttr}
                onClick={onClick}
                className={cn(action && 'pr-8')}
            >
                {icon && (
                    <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4" aria-hidden>
                        {icon}
                    </span>
                )}
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {badge}
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
            </TodayPaneOption>
            {action && (
                <span className="absolute right-1 flex items-center opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100">
                    {action}
                </span>
            )}
        </div>
    )
}
