import { forwardRef } from 'react'

import { cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SEVERITY_INDICATOR, TodayRailSeverity } from './todayRailSeverity'

// The frontend's Tailwind has no quill status fills, so the dot reads the quill variables directly.
const DOT_CLASS = {
    default: 'bg-[var(--primary)]',
    warning: 'bg-[var(--warning-foreground)]',
    destructive: 'bg-[var(--destructive-foreground)]',
} as const

export interface TodayRailTileProps extends Omit<React.HTMLAttributes<HTMLElement>, 'onClick'> {
    label: string
    icon: JSX.Element
    active: boolean
    /** Without a destination the tile renders a button, so it can trigger a menu. */
    to?: string
    onClick?: (event: React.MouseEvent<HTMLElement>) => void
    dataAttr: string
    severity?: TodayRailSeverity
}

export const TodayRailTile = forwardRef<HTMLElement, TodayRailTileProps>(function TodayRailTile(
    { label, icon, active, to, onClick, dataAttr, severity = 'none', ...props },
    ref
): JSX.Element {
    const indicator = SEVERITY_INDICATOR[severity]
    return (
        <LinkPrimitive
            ref={ref}
            aria-label={label}
            {...props}
            to={to}
            aria-current={to && active ? 'page' : undefined}
            data-attr={dataAttr}
            onClick={
                to
                    ? (event) => {
                          // Cmd/ctrl and middle clicks never reach here, so the browser still opens those in a new tab.
                          event.preventDefault()
                          onClick?.(event)
                      }
                    : onClick
            }
            className={cn(
                'group flex w-full shrink-0 cursor-pointer flex-col items-center gap-1 outline-none hover:text-foreground',
                active ? 'text-foreground' : 'text-muted-foreground'
            )}
        >
            <span
                className={cn(
                    'relative flex size-10 items-center justify-center rounded-md [&_svg]:size-5',
                    'group-focus-visible:ring-2 group-focus-visible:ring-[var(--ring)]',
                    active ? 'bg-[var(--fill-selected)]' : 'group-hover:bg-[var(--fill-hover)]'
                )}
            >
                {icon}
                {indicator && (
                    <span
                        aria-hidden
                        className={cn(
                            'absolute -top-0.5 -end-0.5 size-2 rounded-full ring-2 ring-[var(--chrome)]',
                            DOT_CLASS[indicator]
                        )}
                    />
                )}
            </span>
            <span className="max-w-full truncate px-0.5 text-[10px] leading-3 font-medium">{label}</span>
        </LinkPrimitive>
    )
})
