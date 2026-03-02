import { Menu } from '@base-ui/react/menu'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo, useState } from 'react'

import { IconApps } from '@posthog/icons'
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

import { MenuSearchInput } from '~/layout/panel-layout/ai-first/MenuSearchInput'
import { MenuTrigger } from '~/layout/panel-layout/ai-first/MenuTrigger'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { DashboardsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/DashboardsMenuItems'
import { ProductAnalyticsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/ProductAnalyticsMenuItems'
import { SessionReplayMenuItems } from '~/layout/panel-layout/ProjectTree/menus/SessionReplayMenuItems'
import { getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { CATEGORY_ORDER } from '../ProjectTree/utils'

const menuItemStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover'

interface ProductGroup {
    value: string
    items: FileSystemImport[]
}

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
    const [searchTerm, setSearchTerm] = useState('')

    useAppShortcut({
        name: 'open-all-apps-menu',
        keybind: [keyBinds.allApps],
        intent: 'Open all apps menu',
        interaction: 'function',
        callback: () => {
            setOpen((prev) => !prev)
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

    const filteredGroups = useMemo(() => {
        if (!searchTerm) {
            return productGroups
        }
        const term = searchTerm.toLowerCase()
        return productGroups
            .map((group) => ({
                ...group,
                items: group.items.filter((item) => item.path.toLowerCase().includes(term)),
            }))
            .filter((group) => group.items.length > 0)
    }, [productGroups, searchTerm])

    return (
        <Menu.Root
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (!nextOpen) {
                    setSearchTerm('')
                }
            }}
        >
            <MenuTrigger
                label="Apps"
                icon={<IconApps />}
                isCollapsed={isCollapsed}
                tooltip={
                    <>
                        <span>Apps</span> <RenderKeybind keybind={[keyBinds.allApps]} />
                    </>
                }
            />
            <Menu.Portal>
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="right"
                    align="start"
                    sideOffset={6}
                    alignOffset={-4}
                >
                    <Menu.Popup className="primitive-menu-content min-w-[300px] flex flex-col p-1 h-(--available-height)">
                        <MenuSearchInput
                            placeholder="Search apps"
                            value={searchTerm}
                            onChange={(e) => setSearchTerm(e.target.value)}
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <div className="flex flex-col gap-1">
                                {filteredGroups.map((group) => (
                                    <Menu.Group key={group.value} className="flex flex-col gap-px">
                                        <Menu.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                            {group.value}
                                        </Menu.GroupLabel>
                                        {group.items.map((product) => (
                                            <ProductContextMenu
                                                key={product.path}
                                                product={product}
                                                onClick={() => setOpen(false)}
                                            >
                                                <Menu.Item
                                                    className={cn(
                                                        menuItemStyles,
                                                        'group/colorful-product-icons colorful-product-icons-true'
                                                    )}
                                                    label={product.path}
                                                    onClick={() => {
                                                        router.actions.push(product.href || '#')
                                                        setOpen(false)
                                                    }}
                                                    render={
                                                        <ButtonPrimitive menuItem className="hidden lg:flex">
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
                                        ))}
                                    </Menu.Group>
                                ))}
                                {filteredGroups.length === 0 && (
                                    <div className="px-2 py-4 text-center text-sm text-muted">No apps found.</div>
                                )}
                            </div>
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
