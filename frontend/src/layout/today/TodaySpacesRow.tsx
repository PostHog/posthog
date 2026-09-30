import { useState } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayOverflowText } from './TodayOverflowText'

// The label's right padding for the icon-sized slots that sit over the end of the row.
const TRAILING_PADDING = ['', 'pr-8', 'pr-12', 'pr-16', 'pr-20', 'pr-24'] as const

interface TodaySpacesRowProps {
    label: string
    icon: JSX.Element
    to: string
    active: boolean
    dataAttr: string
    action?: JSX.Element | null
    /** Stays visible at the end of the row, after the hover action. */
    badge?: JSX.Element | null
    /** How many icon-sized slots `badge` takes, so the label truncates before them. */
    badgeCount?: 1 | 2 | 3
    /** How many icon buttons `action` holds, so the label truncates before them. */
    actionCount?: 1 | 2
    unread?: boolean
    /** Off when the row's icon already marks it unread. */
    unreadDot?: boolean
    /** Fade a long label and scroll it on hover instead of cutting it with an ellipsis. */
    ticker?: boolean
}

export function TodaySpacesRow({
    label,
    icon,
    to,
    active,
    dataAttr,
    action,
    badge,
    badgeCount = 1,
    actionCount = 1,
    unread = false,
    unreadDot = true,
    ticker = false,
}: TodaySpacesRowProps): JSX.Element {
    const trailingSlots = (action ? actionCount : 0) + (badge ? badgeCount : 0)
    const [hovered, setHovered] = useState(false)
    const [keyboardFocused, setKeyboardFocused] = useState(false)
    return (
        <div
            className="group/row relative flex min-w-0 items-center"
            onPointerEnter={ticker ? () => setHovered(true) : undefined}
            onPointerLeave={ticker ? () => setHovered(false) : undefined}
        >
            <Button
                size="row"
                left
                render={<LinkPrimitive to={to} />}
                aria-current={active ? 'page' : undefined}
                data-attr={dataAttr}
                onFocus={
                    ticker
                        ? (e: React.FocusEvent<HTMLElement>) =>
                              setKeyboardFocused(e.currentTarget.matches(':focus-visible'))
                        : undefined
                }
                onBlur={ticker ? () => setKeyboardFocused(false) : undefined}
                className={cn(
                    'min-w-0 text-xs font-medium text-foreground',
                    active && 'bg-fill-selected',
                    TRAILING_PADDING[trailingSlots]
                )}
            >
                <span className="flex size-3.5 shrink-0 items-center justify-center">{icon}</span>
                {ticker ? (
                    <TodayOverflowText
                        reveal={hovered || keyboardFocused}
                        className={cn('flex-1', unread && 'font-semibold')}
                    >
                        {label}
                    </TodayOverflowText>
                ) : (
                    <span className={cn('min-w-0 flex-1 truncate', unread && 'font-semibold')}>{label}</span>
                )}
                {unread && unreadDot && !active && (
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
