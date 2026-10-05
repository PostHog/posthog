import { Link } from 'lib/lemon-ui/Link'

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
        <Link
            to={to}
            target={target}
            subtle
            className="TodayNavItem"
            data-active={active || current}
            aria-current={current ? 'page' : undefined}
            data-state={state}
            data-attr={dataAttr}
            onClick={onClick}
            onMouseEnter={() => onHoverChange?.(true)}
            onMouseLeave={() => onHoverChange?.(false)}
        >
            <span
                className="TodayNavItem__marker"
                aria-hidden
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--report-color': color } as React.CSSProperties}
            >
                {icon}
            </span>
            <span className="TodayNavItem__copy">
                <span className="TodayNavItem__title">{title}</span>
                <span className="TodayNavItem__meta">{meta}</span>
            </span>
        </Link>
    )
}
