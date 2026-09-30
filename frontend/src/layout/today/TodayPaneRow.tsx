import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

interface TodayPaneRowProps {
    label: string
    meta?: string
    icon?: JSX.Element | null
    to?: string
    active?: boolean
    onClick?: () => void
    trailing?: JSX.Element | null
    /** A control that sits on the row's right edge and shows on hover, outside the row's own link or button. */
    action?: JSX.Element | null
    dataAttr?: string
}

/** One row in the Spaces, Library and Tools sidebars. It is a link when it has `to`, otherwise a button. */
export function TodayPaneRow({
    label,
    meta,
    icon,
    to,
    active = false,
    onClick,
    trailing,
    action,
    dataAttr,
}: TodayPaneRowProps): JSX.Element {
    const content = (
        <>
            {icon && (
                <span className="TodayPaneRow__icon" aria-hidden>
                    {icon}
                </span>
            )}
            <span className="TodayPaneRow__label">{label}</span>
            {meta && <span className="TodayPaneRow__meta">{meta}</span>}
            {trailing}
        </>
    )
    const className = cn('TodayPaneRow', action && 'TodayPaneRow--withAction')
    const row = to ? (
        <Link to={to} className={className} data-active={active} data-attr={dataAttr} subtle onClick={onClick}>
            {content}
        </Link>
    ) : (
        <button type="button" className={className} data-active={active} data-attr={dataAttr} onClick={onClick}>
            {content}
        </button>
    )
    if (!action) {
        return row
    }
    return (
        <div className="TodayPaneRow__wrap">
            {row}
            <span className="TodayPaneRow__action">{action}</span>
        </div>
    )
}
