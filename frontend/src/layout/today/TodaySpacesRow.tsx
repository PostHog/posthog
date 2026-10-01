import { useState } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayOverflowText } from './TodayOverflowText'

// The label's right padding for the icon-sized slots that sit over the end of the row, at rest and on hover.
const TRAILING_PADDING = ['', 'pr-8', 'pr-12', 'pr-16', 'pr-20', 'pr-24'] as const
const HOVER_TRAILING_PADDING = [
    '',
    'group-hover/row:pr-8 group-focus-within/row:pr-8 group-has-[[data-popup-open]]/row:pr-8',
    'group-hover/row:pr-12 group-focus-within/row:pr-12 group-has-[[data-popup-open]]/row:pr-12',
    'group-hover/row:pr-16 group-focus-within/row:pr-16 group-has-[[data-popup-open]]/row:pr-16',
    'group-hover/row:pr-20 group-focus-within/row:pr-20 group-has-[[data-popup-open]]/row:pr-20',
    'group-hover/row:pr-24 group-focus-within/row:pr-24 group-has-[[data-popup-open]]/row:pr-24',
] as const

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
    unread?: boolean
    /** Off when the row's icon already marks it unread. */
    unreadDot?: boolean
    /** Fade a long label and scroll it on hover instead of cutting it with an ellipsis. */
    ticker?: boolean
    /** Part of a multi-session selection, so the row takes Desktop's selected tint. */
    selected?: boolean
    /** Runs before the link navigates, so a modifier click can take the click over. */
    onClickCapture?: (event: React.MouseEvent<HTMLElement>) => void
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
    unread = false,
    unreadDot = true,
    ticker = false,
    selected = false,
    onClickCapture,
}: TodaySpacesRowProps): JSX.Element {
    const [hovered, setHovered] = useState(false)
    const [keyboardFocused, setKeyboardFocused] = useState(false)
    const badgeSlots = badge ? badgeCount : 0
    const actionSlots = action ? 1 : 0
    const showUnreadDot = unread && unreadDot && !active
    // Like PostHog Desktop, a row with badges shows its unread dot after them.
    const trailingDot = showUnreadDot && !!badge
    const restSlots = badgeSlots + (trailingDot ? 1 : 0)
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
                onClickCapture={onClickCapture}
                onFocus={
                    ticker
                        ? (e: React.FocusEvent<HTMLElement>) =>
                              setKeyboardFocused(e.currentTarget.matches(':focus-visible'))
                        : undefined
                }
                onBlur={ticker ? () => setKeyboardFocused(false) : undefined}
                className={cn(
                    'min-w-0 text-xs font-medium text-foreground',
                    // Like Desktop, the open row takes a stronger tint than the other selected rows.
                    selected ? (active ? 'bg-primary/20' : 'bg-primary/10') : active && 'bg-fill-selected',
                    TRAILING_PADDING[restSlots],
                    HOVER_TRAILING_PADDING[restSlots + actionSlots]
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
                {trailingDot ? (
                    <span className="sr-only">Unread</span>
                ) : (
                    showUnreadDot && (
                        <span
                            role="img"
                            aria-label="Unread"
                            className="size-1.5 shrink-0 rounded-full bg-primary"
                            data-attr="today-unread-dot"
                        />
                    )
                )}
            </Button>
            {(action || badge) && (
                // Like PostHog Desktop, the badges sit at the end of the row and move left for the hover action.
                // The action stays while its menu is open, so the menu keeps its anchor after the pointer leaves.
                <div className="absolute right-1 flex min-w-0 items-center gap-0.5">
                    {/* Desktop's spacing between the faces and the unread dot. */}
                    <span className="flex shrink-0 items-center gap-1.5">
                        {badge}
                        {trailingDot && (
                            <span
                                aria-hidden
                                className="mr-1 size-1.5 shrink-0 rounded-full bg-primary"
                                data-attr="today-unread-dot"
                            />
                        )}
                    </span>
                    {action && (
                        <div className="hidden group-focus-within/row:flex group-hover/row:flex group-has-[[data-popup-open]]/row:flex">
                            {action}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
