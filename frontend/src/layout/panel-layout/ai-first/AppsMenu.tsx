import { Combobox } from '@base-ui/react/combobox'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconApps, IconChevronRight } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { cn } from 'lib/utils/css-classes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { DashboardsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/DashboardsMenuItems'
import { ProductAnalyticsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/ProductAnalyticsMenuItems'
import { SessionReplayMenuItems } from '~/layout/panel-layout/ProjectTree/menus/SessionReplayMenuItems'
import { getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'

const menuItemStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover'

interface ProductGroup {
    value: string
    items: FileSystemImport[]
}

const CATEGORY_ORDER = ['Analytics', 'Behavior', 'Features', 'Tools', 'Unreleased']

function ProductContextMenu({
    product,
    onClick,
    children,
}: {
    product: FileSystemImport
    onClick: () => void
    children: React.ReactNode
}): JSX.Element {
    const hasSpecialMenu = ['Product analytics', 'Session replay', 'Dashboards'].includes(product.path)

    if (!hasSpecialMenu) {
        return (
            <ContextMenu>
                <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
                <ContextMenuContent loop className="max-w-[250px]">
                    <ContextMenuGroup>
                        <BrowserLikeMenuItems MenuItem={ContextMenuItem} href={product.href || '#'} onClick={onClick} />
                    </ContextMenuGroup>
                </ContextMenuContent>
            </ContextMenu>
        )
    }

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            <ContextMenuContent loop className="max-w-[250px]">
                <ContextMenuGroup>
                    <BrowserLikeMenuItems MenuItem={ContextMenuItem} href={product.href || '#'} onClick={onClick} />
                </ContextMenuGroup>
                <ContextMenuGroup className="group/colorful-product-icons colorful-product-icons-true">
                    {product.path === 'Product analytics' && (
                        <ProductAnalyticsMenuItems
                            MenuItem={ContextMenuItem}
                            MenuGroup={ContextMenuGroup}
                            onLinkClick={onClick}
                        />
                    )}
                    {product.path === 'Session replay' && <SessionReplayMenuItems onLinkClick={onClick} />}
                    {product.path === 'Dashboards' && <DashboardsMenuItems onLinkClick={onClick} />}
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

export function AppsMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const [open, setOpen] = useState(false)

    useAppShortcut({
        name: 'open-all-apps-menu',
        keybind: [keyBinds.allApps],
        intent: 'Open all apps menu',
        interaction: 'function',
        callback: () => {
            setOpen(!open)
        },
    })

    const productGroups = useMemo(() => {
        const allProducts = getTreeItemsProducts()
        const filteredProducts = allProducts.filter((p) => !p.flag || (featureFlags as Record<string, boolean>)[p.flag])

        const grouped: Record<string, FileSystemImport[]> = {}
        for (const product of filteredProducts) {
            const category = product.category || 'Other'
            if (!grouped[category]) {
                grouped[category] = []
            }
            grouped[category].push(product)
        }

        const groups: ProductGroup[] = CATEGORY_ORDER.filter((cat) => grouped[cat]).map((cat) => ({
            value: cat,
            items: grouped[cat],
        }))

        return groups
    }, [featureFlags])

    return (
        <Combobox.Root
            open={open}
            onOpenChange={setOpen}
            items={productGroups}
            itemToStringValue={(item: FileSystemImport) => item.path}
            defaultInputValue=""
            autoHighlight
        >
            <Combobox.Trigger
                render={
                    <ButtonPrimitive
                        iconOnly={isCollapsed}
                        tooltip={
                            <>
                                <span>Apps</span> <RenderKeybind keybind={[keyBinds.allApps]} />
                            </>
                        }
                        tooltipPlacement="right"
                        menuItem
                        className="hidden lg:flex"
                        onClick={() => setOpen(!open)}
                    >
                        <IconApps className="size-4 text-secondary" />
                        {!isCollapsed && (
                            <>
                                <span className="flex-1 text-left">Apps</span>
                                <IconChevronRight className="size-3 text-secondary" />
                            </>
                        )}
                    </ButtonPrimitive>
                }
            />
            <Combobox.Portal>
                <Combobox.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Combobox.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 max-h-(--available-height)">
                        <Combobox.Input
                            placeholder="Search apps"
                            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
                            autoFocus
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-1">
                                {(group: ProductGroup) => (
                                    <Combobox.Group
                                        key={group.value}
                                        items={group.items}
                                        className="flex flex-col gap-px"
                                    >
                                        <Combobox.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                            {group.value}
                                        </Combobox.GroupLabel>
                                        <Combobox.Collection>
                                            {(product: FileSystemImport) => (
                                                <ProductContextMenu
                                                    key={product.path}
                                                    product={product}
                                                    onClick={() => setOpen(false)}
                                                >
                                                    <Combobox.Item
                                                        value={product}
                                                        className={cn(
                                                            menuItemStyles,
                                                            'group/colorful-product-icons colorful-product-icons-true'
                                                        )}
                                                        onClick={() => {
                                                            router.actions.push(product.href || '#')
                                                            setOpen(false)
                                                        }}
                                                        render={
                                                            <ButtonPrimitive
                                                                iconOnly={isCollapsed}
                                                                menuItem={!isCollapsed}
                                                                className="hidden lg:flex"
                                                            >
                                                                {iconForType(product.iconType)}
                                                                <span className="flex-1">{product.path}</span>
                                                                {product.tags?.includes('beta') && (
                                                                    <LemonTag type="highlight" size="small">
                                                                        BETA
                                                                    </LemonTag>
                                                                )}
                                                                {product.tags?.includes('alpha') && (
                                                                    <LemonTag type="completion" size="small">
                                                                        ALPHA
                                                                    </LemonTag>
                                                                )}
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                </ProductContextMenu>
                                            )}
                                        </Combobox.Collection>
                                    </Combobox.Group>
                                )}
                            </Combobox.List>
                            <Combobox.Empty className="px-2 py-4 text-center text-sm text-muted empty:hidden">
                                No apps found.
                            </Combobox.Empty>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}
