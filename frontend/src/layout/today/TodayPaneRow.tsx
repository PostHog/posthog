import { NavItem, NavItemAction, NavItemButton, NavItemLabel, NavItemMeta } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

interface TodayPaneRowProps {
    label: string
    meta?: string
    icon?: JSX.Element | null
    to?: string
    active?: boolean
    onClick?: () => void
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
    action,
    dataAttr,
}: TodayPaneRowProps): JSX.Element {
    return (
        <NavItem>
            <NavItemButton
                current={active}
                render={to ? <LinkPrimitive to={to} /> : undefined}
                data-attr={dataAttr}
                onClick={onClick}
            >
                {icon}
                <NavItemLabel>{label}</NavItemLabel>
                {meta && <NavItemMeta>{meta}</NavItemMeta>}
            </NavItemButton>
            {action && <NavItemAction>{action}</NavItemAction>}
        </NavItem>
    )
}
