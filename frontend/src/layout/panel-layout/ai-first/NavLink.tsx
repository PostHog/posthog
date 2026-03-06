import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

interface NavLinkProps {
    to: string
    label: string
    icon: React.ReactNode
    isCollapsed: boolean
}

export function NavLink({ to, label, icon, isCollapsed }: NavLinkProps): JSX.Element {
    const { showConfigurePinnedTabsModal } = useActions(navigationLogic)
    const { pathname } = useValues(panelLayoutLogic)

    const isHomePage = to === urls.projectHomepage()
    const currentPath = removeProjectIdIfPresent(pathname)
    const isActive = currentPath === to

    return (
        <ButtonGroupPrimitive
            fullWidth
            className="group/wrapper flex justify-center [&>span]:w-full [&>span]:flex [&>span]:justify-center"
        >
            <Link
                buttonProps={{
                    menuItem: !isCollapsed,
                    iconOnly: isCollapsed,
                    className: 'group',
                    active: isActive,
                    hasSideActionRight: isHomePage,
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
            {isHomePage && (
                <ButtonPrimitive
                    className="opacity-0 group-hover/wrapper:opacity-50 hover:!opacity-100 transition-all duration-50"
                    iconOnly
                    isSideActionRight
                    onClick={(e) => {
                        e.stopPropagation()
                        showConfigurePinnedTabsModal()
                    }}
                    tooltip="Configure tabs & home"
                    tooltipPlacement="right"
                >
                    <IconGear className="size-3 text-tertiary" />
                </ButtonPrimitive>
            )}
        </ButtonGroupPrimitive>
    )
}
