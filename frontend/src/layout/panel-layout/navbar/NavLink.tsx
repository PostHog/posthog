import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent, stripQueryAndHash } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

interface NavLinkProps {
    to: string
    label: string
    icon: React.ReactNode
    isCollapsed: boolean
    'data-attr'?: string
    onClick?: (e: React.MouseEvent) => void
    sideAction?: React.ReactNode
}

export function NavLink({
    to,
    label,
    icon,
    isCollapsed,
    'data-attr': dataAttr,
    onClick,
    sideAction,
}: NavLinkProps): JSX.Element {
    const { pathname } = useValues(panelLayoutLogic)

    // The pathname has no query string, so a filtered destination like `/views?type=canvas` matches on its path
    const toPath = stripQueryAndHash(to)
    const isHomePage = toPath === urls.projectRoot()
    const currentPath = removeProjectIdIfPresent(pathname)
    const isInbox = toPath === urls.inbox()
    const isActive =
        currentPath === toPath ||
        (isHomePage && currentPath === urls.projectHomepage()) ||
        (isInbox && currentPath.startsWith(`${toPath}/`))
    const hasSideActionRight = !!sideAction && !isCollapsed

    return (
        <ButtonGroupPrimitive
            fullWidth
            className="group/nav-link flex justify-center [&>span]:w-full [&>span]:flex [&>span]:justify-center"
        >
            <Link
                buttonProps={{
                    menuItem: !isCollapsed,
                    iconOnly: isCollapsed,
                    // Hovering the side action has to light up the whole row too, like tree items do
                    className: cn(
                        'group -outline-offset-2',
                        hasSideActionRight && 'group-hover/nav-link:bg-fill-button-tertiary-hover'
                    ),
                    active: isActive,
                    hasSideActionRight,
                }}
                to={to}
                data-attr={dataAttr}
                onClick={onClick}
                tooltip={label}
                tooltipPlacement="right"
            >
                <span
                    className={cn(
                        'relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50',
                        isActive && 'text-primary opacity-100'
                    )}
                >
                    {icon}
                </span>
                {!isCollapsed && (
                    <span
                        className={cn(
                            'flex-1 truncate text-left text-secondary group-hover:text-primary',
                            isActive && 'text-primary'
                        )}
                    >
                        {label}
                    </span>
                )}
            </Link>
            {hasSideActionRight && sideAction}
        </ButtonGroupPrimitive>
    )
}
