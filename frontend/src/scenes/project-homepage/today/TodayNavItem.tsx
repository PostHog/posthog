import { Link } from 'lib/lemon-ui/Link'

interface TodayNavItemProps {
    title: string
    meta: string
    color: string
    icon: JSX.Element
    to: string
    /** Highlighted because the matching report is hovered elsewhere on the page. */
    active?: boolean
    current?: boolean
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
    active = false,
    current = false,
    onClick,
    onHoverChange,
    dataAttr,
}: TodayNavItemProps): JSX.Element {
    return (
        <Link
            to={to}
            subtle
            className="TodayNavItem"
            data-active={active || current}
            aria-current={current ? 'page' : undefined}
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
