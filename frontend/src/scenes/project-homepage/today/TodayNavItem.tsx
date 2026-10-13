import { Item, ItemContent, ItemDescription, ItemMedia, ItemTitle, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

interface TodayNavItemProps {
    title: string
    meta: string
    color: string
    icon: JSX.Element
    to: string
    target?: string
    /** Highlighted because the matching report is hovered elsewhere on the page. */
    active?: boolean
    current?: boolean
    /** Crossed out when the item was resolved after the briefing was written, faded when it was dismissed. */
    state?: BriefingItemStateEnumApi
    onClick?: () => void
    onHoverChange?: (hovered: boolean) => void
    dataAttr?: string
}

export function TodayNavItem({
    title,
    meta,
    color,
    icon,
    to,
    target,
    active = false,
    current = false,
    state = 'open',
    onClick,
    onHoverChange,
    dataAttr,
}: TodayNavItemProps): JSX.Element {
    return (
        <Item
            variant="menuItem"
            size="xs"
            render={<LinkPrimitive to={to} target={target} />}
            className={cn(
                'TodayNavItem flex-nowrap pl-[11px] text-foreground no-underline hover:text-foreground',
                (active || current) && 'bg-[var(--fill-selected)]'
            )}
            data-active={active || current}
            aria-current={current ? 'page' : undefined}
            data-state={state}
            data-attr={dataAttr}
            onClick={onClick}
            onMouseEnter={() => onHoverChange?.(true)}
            onMouseLeave={() => onHoverChange?.(false)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--report-color': color } as React.CSSProperties}
        >
            <ItemMedia className="TodayNavItem__marker" aria-hidden>
                {icon}
            </ItemMedia>
            <ItemContent className="min-w-0 gap-0.5">
                <ItemTitle className="TodayNavItem__title w-full font-semibold">
                    <span className="truncate">{title}</span>
                </ItemTitle>
                {meta && <ItemDescription className="truncate">{meta}</ItemDescription>}
            </ItemContent>
        </Item>
    )
}
