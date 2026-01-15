import { Combobox } from '@base-ui-components/react/combobox'
import { Menu } from '@base-ui-components/react/menu'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconEllipsis,
    IconMessage,
    IconPeople,
    IconPlusSmall,
    IconSidebarClose,
    IconSidebarOpen,
} from '@posthog/icons'
import { LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { keybindToKeyboardShortcutProps } from 'lib/components/AppShortcuts/AppShortcut'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { formatConversationDate } from 'scenes/max/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { DashboardsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/DashboardsMenuItems'
import { ProductAnalyticsMenuItems } from '~/layout/panel-layout/ProjectTree/menus/ProductAnalyticsMenuItems'
import { SessionReplayMenuItems } from '~/layout/panel-layout/ProjectTree/menus/SessionReplayMenuItems'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'
import { getTreeItemsProducts } from '~/products'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab, ConversationDetail, ConversationStatus } from '~/types'

import { OrganizationMenu } from '../../lib/components/Account/OrganizationMenu'
import { ProjectMenu } from '../../lib/components/Account/ProjectMenu'
import { KeyboardShortcut } from '../navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { BrowserLikeMenuItems } from './ProjectTree/menus/BrowserLikeMenuItems'

const menuTriggerStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover data-[popup-open]:bg-fill-button-tertiary-hover w-full'
const menuPopupStyles =
    'primitive-menu-content min-w-[200px] z-[var(--z-popover)] outline-none origin-[var(--transform-origin)]'
const menuItemStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover'
const submenuTriggerStyles =
    'flex items-center gap-2 px-2 py-1.5 rounded-sm text-sm cursor-pointer hover:bg-fill-button-tertiary-hover outline-none data-[highlighted]:bg-fill-button-tertiary-hover data-[popup-open]:bg-fill-button-tertiary-hover'

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

function AppsMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const [open, setOpen] = useState(false)

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
            <Combobox.Trigger className={menuTriggerStyles}>
                <IconApps className="size-4 text-secondary" />
                {!isCollapsed && (
                    <>
                        <span className="flex-1 text-left">Apps</span>
                        <IconChevronRight className="size-3 text-secondary" />
                    </>
                )}
            </Combobox.Trigger>
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
                                                    </Combobox.Item>
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

function ConversationContextMenu({
    conversation,
    onClick,
    children,
}: {
    conversation: ConversationDetail
    onClick: () => void
    children: React.ReactNode
}): JSX.Element {
    const conversationUrl = combineUrl(urls.ai(conversation.id), { from: 'history' }).url

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            <ContextMenuContent loop className="max-w-[250px]">
                <ContextMenuGroup>
                    <BrowserLikeMenuItems MenuItem={ContextMenuItem} href={conversationUrl} onClick={onClick} />
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

interface ConversationGroup {
    value: string
    items: ConversationDetail[]
}

const DATE_GROUP_ORDER = ['Today', 'Yesterday', 'Last 7 days', 'Last 30 days', 'Older']

function getDateGroupLabel(dateString: string | null): string {
    if (!dateString) {
        return 'Older'
    }

    const date = new Date(dateString)
    const now = new Date()
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)
    const lastWeek = new Date(today)
    lastWeek.setDate(lastWeek.getDate() - 7)
    const lastMonth = new Date(today)
    lastMonth.setDate(lastMonth.getDate() - 30)

    if (date >= today) {
        return 'Today'
    } else if (date >= yesterday) {
        return 'Yesterday'
    } else if (date >= lastWeek) {
        return 'Last 7 days'
    } else if (date >= lastMonth) {
        return 'Last 30 days'
    }
    return 'Older'
}

function AllConversationsMenu({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const [open, setOpen] = useState(false)
    const { conversationHistory } = useValues(maxGlobalLogic)
    const { searchParams } = useValues(router)
    const currentConversationId = searchParams?.chat

    const conversationGroups = useMemo(() => {
        const grouped: Record<string, ConversationDetail[]> = {}

        for (const conversation of conversationHistory) {
            const groupLabel = getDateGroupLabel(conversation.updated_at)
            if (!grouped[groupLabel]) {
                grouped[groupLabel] = []
            }
            grouped[groupLabel].push(conversation)
        }

        const groups: ConversationGroup[] = DATE_GROUP_ORDER.filter((label) => grouped[label]?.length > 0).map(
            (label) => ({
                value: label,
                items: grouped[label],
            })
        )

        return groups
    }, [conversationHistory])

    useAppShortcut({
        name: 'open-all-chats',
        keybind: [['g', 'then', 'c']],
        intent: 'Open all chats',
        interaction: 'function',
        callback: () => {
            setOpen(!open)
        },
    })

    return (
        <Combobox.Root
            open={open}
            onOpenChange={setOpen}
            items={conversationGroups}
            itemToStringValue={(item: ConversationDetail) => item.title || ''}
            defaultInputValue=""
            autoHighlight
        >
            <Combobox.Trigger
                className={menuTriggerStyles}
                render={
                    <ButtonPrimitive
                        iconOnly={isCollapsed}
                        tooltip={
                            <>
                                <span>All chats</span>{' '}
                                <KeyboardShortcut
                                    preserveOrder
                                    {...keybindToKeyboardShortcutProps(['g', 'then', 'c'])}
                                />
                            </>
                        }
                        tooltipPlacement="right"
                        onClick={() => setOpen(!open)}
                    >
                        <IconEllipsis className="size-4 text-secondary" />
                        {!isCollapsed && (
                            <>
                                <span className="text-left">All chats</span>
                                <IconChevronRight className="size-3 text-secondary ml-auto" />
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
                            placeholder="Search chats"
                            className="w-full px-2 py-1.5 text-sm rounded-sm border border-primary bg-surface-primary focus:outline-none focus:ring-1 focus:ring-primary mb-1"
                            autoFocus
                        />
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" styledScrollbars>
                            <Combobox.List className="flex flex-col gap-1">
                                {(group: ConversationGroup) => (
                                    <Combobox.Group
                                        key={group.value}
                                        items={group.items}
                                        className="flex flex-col gap-px"
                                    >
                                        <Combobox.GroupLabel className="px-2 py-1 text-xs font-medium text-muted sticky top-0 bg-surface-primary z-10">
                                            {group.value}
                                        </Combobox.GroupLabel>
                                        <Combobox.Collection>
                                            {(conversation: ConversationDetail) => (
                                                <ConversationContextMenu
                                                    key={conversation.id}
                                                    conversation={conversation}
                                                    onClick={() => setOpen(false)}
                                                >
                                                    <Combobox.Item
                                                        value={conversation}
                                                        render={
                                                            <Link
                                                                to={
                                                                    combineUrl(urls.ai(conversation.id), {
                                                                        from: 'history',
                                                                    }).url
                                                                }
                                                                buttonProps={{
                                                                    active: conversation.id === currentConversationId,
                                                                    menuItem: true,
                                                                    className: menuItemStyles,
                                                                }}
                                                                tooltip={conversation.title}
                                                                tooltipPlacement="right"
                                                            >
                                                                <span className="flex-1 line-clamp-1">
                                                                    {conversation.title}
                                                                </span>
                                                                {conversation.status ===
                                                                    ConversationStatus.InProgress && (
                                                                    <Spinner className="h-3 w-3" />
                                                                )}
                                                                <span className="text-xs text-tertiary/80 shrink-0">
                                                                    {formatConversationDate(conversation.updated_at)}
                                                                </span>
                                                            </Link>
                                                        }
                                                    />
                                                </ConversationContextMenu>
                                            )}
                                        </Combobox.Collection>
                                    </Combobox.Group>
                                )}
                            </Combobox.List>
                            <Combobox.Empty className="px-2 py-4 text-center text-sm text-muted empty:hidden">
                                No chats found.
                            </Combobox.Empty>
                        </ScrollableShadows>
                    </Combobox.Popup>
                </Combobox.Positioner>
            </Combobox.Portal>
        </Combobox.Root>
    )
}

const navBarStyles = cva({
    base: 'flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-layout-navbar)] relative border-r lg:border-r-transparent',
    variants: {
        isLayoutNavCollapsed: {
            true: 'w-[var(--project-navbar-width-collapsed)]',
            false: 'w-[var(--project-navbar-width)]',
        },
        isMobileLayout: {
            true: 'absolute top-0 bottom-0 left-0',
            false: '',
        },
    },
})

const MAX_RECENT_CONVERSATIONS = 5

function RecentConversations({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { searchParams } = useValues(router)
    const currentConversationId = searchParams?.chat
    const recentConversations = conversationHistory.slice(0, MAX_RECENT_CONVERSATIONS)

    const [loadingStarted, setLoadingStarted] = useState(false)
    const [initialLoadComplete, setInitialLoadComplete] = useState(false)

    useEffect(() => {
        if (conversationHistoryLoading) {
            setLoadingStarted(true)
        } else if (loadingStarted && !initialLoadComplete) {
            setInitialLoadComplete(true)
        }
    }, [conversationHistoryLoading, loadingStarted, initialLoadComplete])

    // Show skeleton until initial load completes
    if (!initialLoadComplete) {
        return (
            <div className="flex flex-col gap-px">
                {Array.from({ length: MAX_RECENT_CONVERSATIONS }).map((_, i) => (
                    <WrappingLoadingSkeleton key={`skeleton-${i}`} fullWidth>
                        <ButtonPrimitive inert aria-hidden>
                            Loading...
                        </ButtonPrimitive>
                    </WrappingLoadingSkeleton>
                ))}
            </div>
        )
    }

    // After load: show empty state or content
    if (recentConversations.length === 0) {
        return (
            <div className="flex flex-col gap-px">
                <div className="text-muted text-xs px-2 py-1">No chats yet</div>
            </div>
        )
    }

    return (
        <div className={cn('flex flex-col gap-px', { 'h-[187px]': recentConversations.length > 0 })}>
            {recentConversations.map((conversation) => {
                const isActive = conversation.id === currentConversationId
                return (
                    <Link
                        key={conversation.id}
                        to={combineUrl(urls.ai(conversation.id), { from: 'history' }).url}
                        buttonProps={{
                            active: isActive,
                            menuItem: true,
                        }}
                        tooltip={conversation.title}
                        tooltipPlacement="right"
                    >
                        <IconMessage className="size-4 text-secondary opacity-50" />
                        {!isCollapsed && (
                            <span className="flex-1 line-clamp-1 text-primary text-sm break-all">
                                {conversation.title}
                            </span>
                        )}
                        {conversation.status === ConversationStatus.InProgress && <Spinner className="h-3 w-3" />}
                    </Link>
                )
            })}
            <AllConversationsMenu isCollapsed={false} />
        </div>
    )
}

export function AiFirstNavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)
    const { toggleLayoutNavCollapsed } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { user } = useValues(userLogic)
    const { firstTabIsActive } = useValues(sceneLogic)

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={cn(
                        navBarStyles({
                            isLayoutNavCollapsed,
                            isMobileLayout,
                        })
                    )}
                    ref={containerRef}
                >
                    <div
                        className={cn(
                            'flex justify-between p-1 pl-[5px] items-center',
                            isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'
                        )}
                    >
                        <div
                            className={cn('flex gap-1 rounded-md w-full', {
                                'flex-col items-center pt-px': isLayoutNavCollapsed,
                            })}
                        >
                            <OrganizationMenu
                                showName={false}
                                buttonProps={{
                                    variant: 'panel',
                                    className: cn('px-px', {
                                        hidden: isLayoutNavCollapsed,
                                    }),
                                    iconOnly: isLayoutNavCollapsed,
                                    tooltipCloseDelayMs: 0,
                                    tooltipPlacement: 'bottom',
                                    tooltip: 'Switch organization',
                                }}
                            />
                            <ProjectMenu
                                buttonProps={{
                                    className: 'max-w-[175px]',
                                    variant: 'panel',
                                    tooltipCloseDelayMs: 0,
                                    iconOnly: isLayoutNavCollapsed,
                                    tooltipPlacement: 'bottom',
                                    tooltip: 'Switch project',
                                }}
                            />

                            {/* <RecentItemsMenu /> */}
                        </div>
                    </div>

                    <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                        <div className="flex-1 show-scrollbar-on-hover">
                            <div className="flex flex-col gap-px">
                                <div
                                    className={cn('px-1 flex flex-col gap-2', {
                                        'items-center': isLayoutNavCollapsed,
                                    })}
                                >
                                    <ButtonPrimitive
                                        iconOnly={isLayoutNavCollapsed}
                                        tooltip={isLayoutNavCollapsed ? 'New chat' : undefined}
                                        tooltipPlacement="right"
                                        onClick={() => router.actions.push(urls.ai())}
                                        menuItem={!isLayoutNavCollapsed}
                                        className="bg-white dark:bg-black border border-secondary shadow"
                                        variant="default"
                                    >
                                        <IconPlusSmall className="size-4 text-secondary" />
                                        New chat
                                    </ButtonPrimitive>

                                    <div className="flex flex-col gap-1">
                                        <Label intent="menu" className="text-xxs px-2 text-tertiary">
                                            Recent
                                        </Label>
                                        <RecentConversations isCollapsed={isLayoutNavCollapsed} />
                                    </div>

                                    <div className="flex flex-col gap-px w-full">
                                        {/* Data Menu */}
                                        <Menu.Root>
                                            <Menu.Trigger className={menuTriggerStyles}>
                                                <IconDatabase className="size-4 text-secondary" />
                                                {!isLayoutNavCollapsed && (
                                                    <>
                                                        <span className="flex-1 text-left">Data</span>
                                                        <IconChevronRight className="size-3 text-secondary" />
                                                    </>
                                                )}
                                            </Menu.Trigger>
                                            <Menu.Portal>
                                                <Menu.Positioner
                                                    className={menuPopupStyles}
                                                    side="right"
                                                    align="start"
                                                    sideOffset={6}
                                                    alignOffset={-4}
                                                >
                                                    <Menu.Popup className="primitive-menu-content-inner flex flex-col gap-px p-1">
                                                        <Menu.Item
                                                            className={menuItemStyles}
                                                            onClick={() =>
                                                                router.actions.push(
                                                                    urls.activity(ActivityTab.ExploreEvents)
                                                                )
                                                            }
                                                        >
                                                            <IconClock className="size-4 text-secondary" />
                                                            Activity
                                                        </Menu.Item>
                                                        <Menu.Item
                                                            className={menuItemStyles}
                                                            onClick={() => router.actions.push(urls.persons())}
                                                        >
                                                            <IconPeople className="size-4 text-secondary" />
                                                            Persons
                                                        </Menu.Item>

                                                        {/* Data management submenu */}
                                                        <Menu.SubmenuRoot>
                                                            <Menu.SubmenuTrigger className={submenuTriggerStyles}>
                                                                {iconForType('data_warehouse')}
                                                                <span className="flex-1">Data management</span>
                                                                <IconChevronRight className="size-3 text-secondary" />
                                                            </Menu.SubmenuTrigger>
                                                            <Menu.Portal>
                                                                <Menu.Positioner
                                                                    className={menuPopupStyles}
                                                                    alignOffset={-4}
                                                                >
                                                                    <Menu.Popup className="primitive-menu-content-inner flex flex-col gap-px p-1">
                                                                        <Menu.Item
                                                                            className={menuItemStyles}
                                                                            onClick={() =>
                                                                                router.actions.push(
                                                                                    urls.eventDefinitions()
                                                                                )
                                                                            }
                                                                        >
                                                                            {iconForType('event_definition')}
                                                                            Events
                                                                        </Menu.Item>
                                                                        <Menu.Item
                                                                            className={menuItemStyles}
                                                                            onClick={() =>
                                                                                router.actions.push(
                                                                                    urls.propertyDefinitions()
                                                                                )
                                                                            }
                                                                        >
                                                                            {iconForType('property_definition')}
                                                                            Properties
                                                                        </Menu.Item>
                                                                        <Menu.Item
                                                                            className={menuItemStyles}
                                                                            onClick={() =>
                                                                                router.actions.push(urls.annotations())
                                                                            }
                                                                        >
                                                                            {iconForType('annotation')}
                                                                            Annotations
                                                                        </Menu.Item>
                                                                        <Menu.Item
                                                                            className={menuItemStyles}
                                                                            onClick={() =>
                                                                                router.actions.push(
                                                                                    urls.dataManagementHistory()
                                                                                )
                                                                            }
                                                                        >
                                                                            <IconClock className="size-4 text-secondary" />
                                                                            History
                                                                        </Menu.Item>
                                                                    </Menu.Popup>
                                                                </Menu.Positioner>
                                                            </Menu.Portal>
                                                        </Menu.SubmenuRoot>

                                                        <Menu.Item
                                                            className={menuItemStyles}
                                                            onClick={() => router.actions.push(urls.groups(0))}
                                                        >
                                                            {iconForType('group')}
                                                            Groups
                                                        </Menu.Item>
                                                    </Menu.Popup>
                                                </Menu.Positioner>
                                            </Menu.Portal>
                                        </Menu.Root>

                                        {/* Apps Menu */}
                                        <AppsMenu isCollapsed={isLayoutNavCollapsed} />
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div className="border-b border-primary h-px " />

                        <div className="p-1 flex flex-col gap-px items-center">
                            <DebugNotice isCollapsed={isLayoutNavCollapsed} />
                            <NavPanelAdvertisement />

                            <ButtonPrimitive
                                iconOnly={isLayoutNavCollapsed}
                                tooltip={isLayoutNavCollapsed ? 'Expand nav' : undefined}
                                tooltipPlacement="right"
                                onClick={() => toggleLayoutNavCollapsed(!isLayoutNavCollapsed)}
                                menuItem={!isLayoutNavCollapsed}
                                className="hidden lg:flex"
                            >
                                {isLayoutNavCollapsed ? (
                                    <>
                                        <IconSidebarClose className="text-tertiary" />
                                    </>
                                ) : (
                                    <>
                                        <IconSidebarOpen className="text-tertiary" />
                                        Collapse nav
                                    </>
                                )}
                            </ButtonPrimitive>

                            <AccountMenu
                                align="end"
                                side="right"
                                alignOffset={10}
                                trigger={
                                    <ButtonPrimitive
                                        menuItem={!isLayoutNavCollapsed}
                                        tooltip={isLayoutNavCollapsed ? 'Account' : undefined}
                                        tooltipPlacement="right"
                                        iconOnly={isLayoutNavCollapsed}
                                        data-attr="menu-item-me"
                                    >
                                        <ProfilePicture user={user} size="xs" />
                                        {!isLayoutNavCollapsed && (
                                            <>
                                                {user?.first_name ? (
                                                    <span>{user?.first_name}</span>
                                                ) : (
                                                    <span>{user?.email}</span>
                                                )}
                                                <IconChevronRight className="size-3 text-secondary ml-auto" />
                                            </>
                                        )}
                                    </ButtonPrimitive>
                                }
                            />
                        </div>
                    </div>
                    {!isMobileLayout && (
                        <Resizer
                            logicKey="panel-layout-navbar"
                            placement="right"
                            containerRef={containerRef}
                            closeThreshold={100}
                            onToggleClosed={(shouldBeClosed) => toggleLayoutNavCollapsed(shouldBeClosed)}
                            onDoubleClick={() => toggleLayoutNavCollapsed()}
                            data-attr="tree-navbar-resizer"
                            // top + 7px is to match rounded-lg border-radius on <main>
                            className={cn('top-[calc(var(--scene-layout-header-height)+7px)] right-[-1px] bottom-4', {
                                // // If first tab is not active, we move the line down to match up with the curve (only present if not first tab is active)
                                'top-[var(--scene-layout-header-height)]': firstTabIsActive,
                                'top-0': isLayoutPanelVisible,
                            })}
                            offset={0}
                        />
                    )}
                </nav>
            </div>
            <ConfigurePinnedTabsModal
                isOpen={isConfigurePinnedTabsOpen}
                onClose={() => setIsConfigurePinnedTabsOpen(false)}
            />
        </>
    )
}
