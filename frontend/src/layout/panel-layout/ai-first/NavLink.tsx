import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
export interface NavLinkSideAction {
    onClick: (e: React.MouseEvent) => void
    tooltip: string
    'data-attr'?: string
}

interface NavLinkProps {
    to: string
    label: string
    icon: React.ReactNode
    isCollapsed: boolean
    'data-attr'?: string
    onClick?: (e: React.MouseEvent) => void
    sideAction?: NavLinkSideAction
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

    const isHomePage = to === urls.projectRoot()
    const currentPath = removeProjectIdIfPresent(pathname)
    const isActive = currentPath === to || (isHomePage && currentPath === urls.projectHomepage())
    const hasSideActionRight = !!sideAction && !isCollapsed

    return (
        <ButtonGroupPrimitive
            fullWidth
            className="group/wrapper flex justify-center [&>span]:w-full [&>span]:flex [&>span]:justify-center"
        >
            <Link
                buttonProps={{
                    menuItem: !isCollapsed,
                    iconOnly: isCollapsed,
                    className: 'group -outline-offset-2',
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
            {hasSideActionRight && sideAction && (
                <ButtonPrimitive
                    className="group -outline-offset-2"
                    iconOnly
                    isSideActionRight
                    onClick={(e) => {
                        e.stopPropagation()
                        sideAction.onClick(e)
                    }}
                    tooltip={sideAction.tooltip}
                    tooltipPlacement="right"
                    data-attr={sideAction['data-attr']}
                >
                    <IconGear className="size-3 text-tertiary opacity-70 group-hover:text-primary group-hover:opacity-100" />
                </ButtonPrimitive>
            )}
        </ButtonGroupPrimitive>
    )
}
