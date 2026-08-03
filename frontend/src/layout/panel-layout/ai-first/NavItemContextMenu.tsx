import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconGear, IconHome } from '@posthog/icons'

import { IconArrowDown, IconArrowUp, IconEyeHidden } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { urls } from 'scenes/urls'

import { DEFAULT_SIDEBAR_ITEM_ORDER } from '~/layout/panel-layout/sidebarCustomization'
import { SidebarItemKey, orderKeys, uiCustomizationLogic, withKeyMovedAmong } from '~/layout/uiCustomizationLogic'

interface NavItemContextMenuProps {
    /** Identity used for ordering; absent for items that cannot be reordered. */
    orderKey?: string
    /** Configuration key used for hiding; absent for items that always stay visible. */
    configKey?: SidebarItemKey
    label: string
    /** Ordered orderKeys of the items currently rendered, so moves skip hidden neighbors. */
    renderedOrderKeys: string[]
    /** Adds a "Change homepage" entry, for the Home item. */
    isHomeItem?: boolean
    children: React.ReactNode
}

/**
 * Right-click menu on main sidebar items: hide, reorder, and shortcuts into the
 * customization settings, so customization is available at the moment of intent.
 */
export function NavItemContextMenu({
    orderKey,
    configKey,
    label,
    renderedOrderKeys,
    isHomeItem,
    children,
}: NavItemContextMenuProps): JSX.Element {
    const { uiCustomizationEnabled, sidebarItemOrder } = useValues(uiCustomizationLogic)
    const { setSidebarItemShown, setSidebarItemOrder } = useActions(uiCustomizationLogic)

    if (!uiCustomizationEnabled) {
        return <>{children}</>
    }

    const fullOrder = orderKeys(DEFAULT_SIDEBAR_ITEM_ORDER, sidebarItemOrder)
    const moveItem = (direction: 1 | -1): void => {
        if (!orderKey) {
            return
        }
        const next = withKeyMovedAmong(fullOrder, renderedOrderKeys, orderKey, direction)
        if (next) {
            setSidebarItemOrder(next)
        }
    }
    const canMoveUp = !!orderKey && renderedOrderKeys.indexOf(orderKey) > 0
    const canMoveDown =
        !!orderKey &&
        renderedOrderKeys.indexOf(orderKey) !== -1 &&
        renderedOrderKeys.indexOf(orderKey) < renderedOrderKeys.length - 1

    return (
        <ContextMenu
            onOpenChange={(open) => {
                if (open) {
                    posthog.capture('nav item context menu opened', { item: orderKey ?? configKey ?? label })
                }
            }}
        >
            <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            <ContextMenuContent loop className="max-w-[250px]">
                {orderKey && (
                    <ContextMenuGroup>
                        <ContextMenuItem asChild disabled={!canMoveUp}>
                            <ButtonPrimitive menuItem disabled={!canMoveUp} onClick={() => moveItem(-1)}>
                                <IconArrowUp className="size-4 text-tertiary" />
                                Move up
                            </ButtonPrimitive>
                        </ContextMenuItem>
                        <ContextMenuItem asChild disabled={!canMoveDown}>
                            <ButtonPrimitive menuItem disabled={!canMoveDown} onClick={() => moveItem(1)}>
                                <IconArrowDown className="size-4 text-tertiary" />
                                Move down
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    </ContextMenuGroup>
                )}
                {configKey && (
                    <ContextMenuGroup>
                        <ContextMenuItem asChild>
                            <ButtonPrimitive menuItem onClick={() => setSidebarItemShown(configKey, false)}>
                                <IconEyeHidden className="size-4 text-tertiary" />
                                Hide from sidebar
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    </ContextMenuGroup>
                )}
                {isHomeItem && (
                    <ContextMenuGroup>
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => router.actions.push(urls.settings('user-navigation', 'homepage'))}
                            >
                                <IconHome className="size-4 text-tertiary" />
                                Change homepage
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    </ContextMenuGroup>
                )}
                <ContextMenuSeparator />
                <ContextMenuGroup>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => router.actions.push(urls.settings('user-navigation'))}>
                            <IconGear className="size-4 text-tertiary" />
                            Customize sidebar
                        </ButtonPrimitive>
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}
