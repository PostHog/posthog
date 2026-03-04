import { Link } from 'lib/lemon-ui/Link'

interface NavLinkProps {
    to: string
    label: string
    icon: React.ReactNode
    isCollapsed: boolean
}

export function NavLink({ to, label, icon, isCollapsed }: NavLinkProps): JSX.Element {
    return (
        <Link
            buttonProps={{
                menuItem: !isCollapsed,
                iconOnly: isCollapsed,
                className: 'group',
            }}
            to={to}
            tooltip={isCollapsed ? label : undefined}
            tooltipPlacement="right"
        >
            <span className="size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                {icon}
            </span>
            {!isCollapsed && <span className="flex-1 text-left">{label}</span>}
        </Link>
    )
}
