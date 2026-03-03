import { Menu } from '@base-ui/react/menu'

import { IconChevronRight } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

interface MenuTriggerProps {
    label: string
    icon: React.ReactNode
    isCollapsed: boolean
    tooltip?: React.ReactNode
}

export function MenuTrigger({ label, icon, isCollapsed, tooltip }: MenuTriggerProps): JSX.Element {
    return (
        <Menu.Trigger
            render={
                <ButtonPrimitive
                    menuItem={!isCollapsed}
                    iconOnly={isCollapsed}
                    tooltip={tooltip ?? (isCollapsed ? label : undefined)}
                    tooltipPlacement="right"
                    className="group"
                >
                    <span className="size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                        {icon}
                    </span>
                    {!isCollapsed && (
                        <>
                            <span className="flex-1 text-left">{label}</span>
                            <IconChevronRight className="size-3 text-secondary" />
                        </>
                    )}
                </ButtonPrimitive>
            }
        />
    )
}
