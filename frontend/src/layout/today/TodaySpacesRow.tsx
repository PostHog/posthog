import { Fragment, useState } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayListItemDetail } from './todayListAppearance'
import { TodayOverflowText } from './TodayOverflowText'

// The label's right padding for the icon-sized slots that sit over the end of the row.
const TRAILING_PADDING = ['', 'pr-8', 'pr-12', 'pr-16', 'pr-20'] as const

interface TodaySpacesRowProps {
    label: string
    icon: JSX.Element
    to: string
    active: boolean
    dataAttr: string
    /** Stays visible at the end of the row. Like Desktop, the row has no hover buttons to make room for. */
    badge?: JSX.Element | null
    /** How many icon-sized slots `badge` takes, so the label truncates before them. */
    badgeCount?: 1 | 2 | 3
    unread?: boolean
    /** Fade a long label and scroll it on hover instead of cutting it with an ellipsis. */
    ticker?: boolean
    /** Part of a multi-session selection, so the row takes Desktop's selected tint. */
    selected?: boolean
    /** Runs before the link navigates, so a modifier click can take the click over. */
    onClickCapture?: (event: React.MouseEvent<HTMLElement>) => void
    /** A second line under the label, like Desktop's list item appearance. Empty keeps the row on one line. */
    details?: TodayListItemDetail[]
}

export function TodaySpacesRow({
    label,
    icon,
    to,
    active,
    dataAttr,
    badge,
    badgeCount = 1,
    unread = false,
    ticker = false,
    selected = false,
    onClickCapture,
    details = [],
}: TodaySpacesRowProps): JSX.Element {
    const [hovered, setHovered] = useState(false)
    const [keyboardFocused, setKeyboardFocused] = useState(false)
    const badgeSlots = badge ? badgeCount : 0
    const showUnreadDot = unread && !active
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
                    'min-w-0 font-medium text-foreground',
                    // Desktop's two-line row: the second line outgrows the fixed row height, so padding stands in for it.
                    details.length > 0 && 'h-auto py-1',
                    // Like Desktop, the open row takes a stronger tint than the other selected rows.
                    selected ? (active ? 'bg-primary/20' : 'bg-primary/10') : active && 'bg-fill-selected',
                    TRAILING_PADDING[badgeSlots]
                )}
            >
                <span
                    className={cn(
                        'flex size-3.5 shrink-0 items-center justify-center',
                        details.length > 0 && 'self-start pt-0.5'
                    )}
                >
                    {showUnreadDot ? (
                        <span
                            role="img"
                            aria-label="Unread"
                            className="size-2 rounded-full bg-primary"
                            data-attr="today-unread-dot"
                        />
                    ) : (
                        icon
                    )}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                    {ticker ? (
                        <TodayOverflowText
                            reveal={hovered || keyboardFocused}
                            className={cn(unread && 'font-semibold')}
                        >
                            {label}
                        </TodayOverflowText>
                    ) : (
                        <span className={cn('min-w-0 truncate', unread && 'font-semibold')}>{label}</span>
                    )}
                    {details.length > 0 && (
                        <span className="truncate text-xxs text-muted-foreground">
                            {details.map((detail, index) => (
                                // Every part is its own element, so a page translator can't break the line when the details change.
                                <Fragment key={detail.field}>
                                    {index > 0 && <span> · </span>}
                                    <span title={detail.title}>{detail.text}</span>
                                </Fragment>
                            ))}
                        </span>
                    )}
                </span>
            </Button>
            {badge && (
                // Like PostHog Desktop, the badges sit at the end of the row.
                <div className="absolute right-1 flex min-w-0 items-center gap-0.5">
                    <span className="flex shrink-0 items-center gap-1.5">{badge}</span>
                </div>
            )}
        </div>
    )
}
