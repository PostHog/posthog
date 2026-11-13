import { forwardRef } from 'react'

import { cn } from '@posthog/quill'

import { SEVERITY_DOT_CLASS, SEVERITY_INDICATOR, TodayRailSeverity } from './todayRailSeverity'

export interface TodayTabBarTabProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    label: string
    icon: JSX.Element
    active: boolean
    dataAttr: string
    severity?: TodayRailSeverity
}

/** A tab in the phone layout's bottom bar. It is what `TodayRailTile` is on the rail. */
export const TodayTabBarTab = forwardRef<HTMLButtonElement, TodayTabBarTabProps>(function TodayTabBarTab(
    { label, icon, active, dataAttr, severity = 'none', className, ...props },
    ref
): JSX.Element {
    const indicator = SEVERITY_INDICATOR[severity]
    return (
        <button
            ref={ref}
            type="button"
            {...props}
            data-attr={dataAttr}
            className={cn(
                'flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-md text-xxs font-medium outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-inset [&_svg]:size-5',
                active ? 'bg-fill-selected text-foreground' : 'text-muted-foreground',
                className
            )}
        >
            <span className="relative flex">
                {icon}
                {indicator && (
                    <span
                        aria-hidden
                        className={cn(
                            'absolute -top-0.5 -end-0.5 size-2 rounded-full ring-2 ring-[var(--today-paper)]',
                            SEVERITY_DOT_CLASS[indicator]
                        )}
                    />
                )}
            </span>
            <span className="max-w-full truncate">{label}</span>
        </button>
    )
})
