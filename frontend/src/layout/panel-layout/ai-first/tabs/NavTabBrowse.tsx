import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { Fragment } from 'react'

import {
    IconApps,
    IconCheck,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNotification,
    IconPencil,
    IconPin,
    IconSearch,
} from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { RenderKeybind } from 'lib/components/Shortcuts/ShortcutMenu'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { NavItemContextMenu } from '~/layout/panel-layout/ai-first/NavItemContextMenu'
import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { NavPinned } from '~/layout/panel-layout/ai-first/NavPinned'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { customProductsLogic } from '~/layout/panel-layout/ProjectTree/customProductsLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { DEFAULT_SIDEBAR_ITEM_ORDER } from '~/layout/panel-layout/sidebarCustomization'
import { SidebarItemKey, orderKeys, uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { BrowserLikeMenuItems } from '../../ProjectTree/menus/BrowserLikeMenuItems'
import { PanelIndicatorIcon, SectionTrigger } from '../Nav'
import { editToolsLogic } from './editToolsLogic'
import { navRecentsLogic } from './navRecentsLogic'

interface ProjectNavItemDef {
    orderKey: string
    /** Absent for items that always stay visible (Activity). */
    configKey?: SidebarItemKey
    label: string
    icon: React.ReactNode
    kind: 'link' | 'trigger'
    to?: string
    identifier?: PanelLayoutNavIdentifier
    tag?: 'alpha' | 'beta' | 'new'
    isHome?: boolean
}

function getItemName(item: FileSystemEntry): string {
    const pathSplit = splitPath(item.path)
    const lastPart = pathSplit.pop()
    return unescapePath(lastPart ?? item.path)
}

function formatRelativeDate(dateStr: string | null | undefined): string {
    if (!dateStr) {
        return ''
    }
    const date = new Date(dateStr)
    if (isNaN(date.getTime())) {
        return ''
    }
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1) {
        return 'now'
    }
    if (diffMins < 60) {
        return `${diffMins}m`
    }
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) {
        return `${diffHours}h`
    }
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 30) {
        return `${diffDays}d`
    }
    const diffMonths = Math.floor(diffDays / 30)
    return `${diffMonths}mo`
}

function usePinnedState(item: FileSystemEntry): {
    isAlreadyPinned: boolean
    addShortcutItem: (item: FileSystemEntry) => void
} {
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    const { shortcutNonFolderPaths } = useValues(projectTreeDataLogic)
    const shortcutPath = joinPath([splitPath(item.path).pop() ?? 'Unnamed'])
    return { isAlreadyPinned: shortcutNonFolderPaths.has(shortcutPath), addShortcutItem }
}

function PinToSidebarDropdownAction({ item }: { item: FileSystemEntry }): JSX.Element {
    const { isAlreadyPinned, addShortcutItem } = usePinnedState(item)

    if (isAlreadyPinned) {
        return (
            <DropdownMenuGroup>
                <BrowserLikeMenuItems MenuItem={DropdownMenuItem} href={item.href ?? ''} />
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild disabled>
                    <ButtonPrimitive menuItem disabled>
                        <IconPin className="size-4 text-tertiary" />
                        Already pinned
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuGroup>
        )
    }

    return (
        <DropdownMenuGroup>
            <BrowserLikeMenuItems MenuItem={DropdownMenuItem} href={item.href ?? ''} />
            <DropdownMenuSeparator />

            <DropdownMenuItem asChild>
                <ButtonPrimitive menuItem onClick={() => addShortcutItem(item)}>
                    <IconPin className="size-4 text-tertiary" />
                    Pin to sidebar
                </ButtonPrimitive>
            </DropdownMenuItem>
        </DropdownMenuGroup>
    )
}

/** Hidden sidebar items stay reachable here (and through search) instead of disappearing entirely. */
function MoreMenu({
    hiddenDefs,
    onTriggerClick,
}: {
    hiddenDefs: ProjectNavItemDef[]
    onTriggerClick: (identifier: PanelLayoutNavIdentifier) => void
}): JSX.Element {
    return (
        <DropdownMenu
            onOpenChange={(open) => {
                if (open) {
                    posthog.capture('nav more menu opened', { hidden_items: hiddenDefs.map((def) => def.orderKey) })
                }
            }}
        >
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive menuItem className="group -outline-offset-2" data-attr="nav-more-menu">
                    <span className="relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                        <IconChevronRight className="rotate-90" />
                    </span>
                    <span className="truncate text-secondary group-hover:text-primary">More</span>
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent side="bottom" align="start" className="min-w-[200px]">
                <DropdownMenuGroup>
                    {hiddenDefs.map((def) =>
                        def.kind === 'link' ? (
                            <DropdownMenuItem key={def.orderKey} asChild>
                                <Link
                                    to={def.to}
                                    buttonProps={{ menuItem: true }}
                                    data-attr={`nav-more-item-${def.orderKey}`}
                                    onClick={() =>
                                        posthog.capture('nav item clicked', { item: def.orderKey, from: 'more-menu' })
                                    }
                                >
                                    <span className="flex size-4 text-tertiary items-center justify-center">
                                        {def.icon}
                                    </span>
                                    {def.label}
                                </Link>
                            </DropdownMenuItem>
                        ) : (
                            <DropdownMenuItem key={def.orderKey} asChild>
                                <ButtonPrimitive
                                    menuItem
                                    data-attr={`nav-more-item-${def.orderKey}`}
                                    onClick={() => def.identifier && onTriggerClick(def.identifier)}
                                >
                                    <span className="flex size-4 text-tertiary items-center justify-center">
                                        {def.icon}
                                    </span>
                                    {def.label}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        )
                    )}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings('user-navigation')}
                            buttonProps={{ menuItem: true }}
                            data-attr="nav-more-customize"
                        >
                            <IconGear className="size-4 text-tertiary" />
                            Customize sidebar
                        </Link>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export function NavTabBrowse(): JSX.Element {
    const { showLayoutPanel, setActivePanelIdentifier, clearActivePanelIdentifier, toggleNavSection } =
        useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        isLayoutNavCollapsed,
        expandedNavSections,
        activePanelIdentifier,
        activePanelIdentifierFromUrlAiFirst,
        pathname,
    } = useValues(panelLayoutLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const { recentItems, recentItemsLoading } = useValues(navRecentsLogic)
    const { isSidebarSectionShown, isSidebarItemShown, uiCustomizationEnabled, sidebarItemOrder, isSidebarFlattened } =
        useValues(uiCustomizationLogic)
    const { enabledToolPaths } = useValues(customProductsLogic)
    // Flag-off path: the pre-customization edit mode and home modal.
    const { isEditMode, checkedTools } = useValues(editToolsLogic)
    const { enterEditMode, saveAndExitEditMode, toggleTool } = useActions(editToolsLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const { toggleCommand } = useActions(commandLogic)
    const showToolsSearchRow = featureFlags[FEATURE_FLAGS.CMD_K_NAV_EXPERIMENT] === 'tools-row' && !isLayoutNavCollapsed
    const currentPath = removeProjectIdIfPresent(pathname)
    const flattened = isSidebarFlattened && !isLayoutNavCollapsed

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        const isOpening = activePanelIdentifier !== item
        posthog.capture('nav panel trigger clicked', { panel: item, is_open: isOpening })
        if (isOpening) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    const allDefs: ProjectNavItemDef[] = [
        {
            orderKey: 'home',
            configKey: 'home',
            label: 'Home',
            icon: <IconHome />,
            kind: 'link',
            to: urls.projectRoot(),
            isHome: true,
        },
        ...(isProductAutonomyEnabled
            ? [
                  {
                      orderKey: 'inbox',
                      configKey: 'inbox' as SidebarItemKey,
                      label: 'Inbox',
                      icon: <IconNotification />,
                      kind: 'link' as const,
                      to: urls.inbox(),
                      tag: 'beta' as const,
                  },
              ]
            : []),
        {
            orderKey: 'activity',
            label: 'Activity',
            icon: <IconClock />,
            kind: 'link',
            to: urls.activity(ActivityTab.ExploreEvents),
        },
        {
            orderKey: 'data',
            configKey: 'data',
            label: 'Data',
            icon: <IconDatabase />,
            kind: 'trigger',
            identifier: 'DataAndPeople',
        },
        {
            orderKey: 'files',
            configKey: 'files',
            label: 'Files',
            icon: <IconFolderOpen className="stroke-[1.2]" />,
            kind: 'trigger',
            identifier: 'Project',
        },
        {
            orderKey: 'tools',
            configKey: 'tools',
            label: 'Tools',
            icon: <IconApps />,
            kind: 'trigger',
            identifier: 'Products',
        },
    ]
    const defsByOrderKey = new Map(allDefs.map((def) => [def.orderKey, def]))
    const orderedDefs = orderKeys(DEFAULT_SIDEBAR_ITEM_ORDER, sidebarItemOrder)
        .map((orderKey) => defsByOrderKey.get(orderKey))
        .filter((def): def is ProjectNavItemDef => !!def)
    const visibleDefs = orderedDefs.filter((def) => !def.configKey || isSidebarItemShown(def.configKey))
    const hiddenDefs = uiCustomizationEnabled
        ? orderedDefs.filter((def) => def.configKey && !isSidebarItemShown(def.configKey))
        : []
    const renderedOrderKeys = visibleDefs.map((def) => def.orderKey)
    const showPinned = uiCustomizationEnabled && !isLayoutNavCollapsed && isSidebarItemShown('starred')
    const pinnedTriggerDef: ProjectNavItemDef = {
        orderKey: 'starred',
        configKey: 'starred',
        label: 'Pinned',
        icon: <IconPin />,
        kind: 'trigger',
        identifier: 'Shortcuts',
    }
    if (uiCustomizationEnabled && !isSidebarItemShown('starred')) {
        // A hidden pinned section stays reachable through the More menu, where it opens the panel.
        hiddenDefs.push(pinnedTriggerDef)
    } else if (uiCustomizationEnabled && isLayoutNavCollapsed && isSidebarItemShown('starred')) {
        // The inline pinned list has no room in collapsed mode, so pins open as a panel instead.
        visibleDefs.push(pinnedTriggerDef)
    }

    const renderLinkDef = (def: ProjectNavItemDef): JSX.Element => (
        <NavItemContextMenu
            key={def.orderKey}
            orderKey={def.orderKey}
            configKey={def.configKey}
            label={def.label}
            renderedOrderKeys={renderedOrderKeys}
            isHomeItem={def.isHome}
        >
            <span className="block w-full">
                <NavLink
                    to={def.to ?? ''}
                    label={def.label}
                    icon={def.icon}
                    isCollapsed={isLayoutNavCollapsed}
                    data-attr={`nav-item-${def.orderKey}`}
                    tag={def.tag}
                    onClick={() => posthog.capture('nav item clicked', { item: def.orderKey })}
                    sideAction={
                        def.isHome
                            ? {
                                  onClick: () =>
                                      uiCustomizationEnabled
                                          ? router.actions.push(urls.settings('user-navigation', 'homepage'))
                                          : showConfigureHomeModal(),
                                  tooltip: 'Configure home',
                                  'data-attr': 'nav-configure-home',
                              }
                            : undefined
                    }
                />
            </span>
        </NavItemContextMenu>
    )

    const renderTriggerDef = (def: ProjectNavItemDef): JSX.Element => {
        const isActive =
            activePanelIdentifier === def.identifier || activePanelIdentifierFromUrlAiFirst === def.identifier
        const tooltip = isLayoutNavCollapsed
            ? isLayoutPanelVisible && activePanelIdentifier === def.identifier
                ? `Close ${def.label.toLowerCase()}`
                : `Open ${def.label.toLowerCase()}`
            : undefined

        return (
            <Fragment key={def.orderKey}>
                <NavItemContextMenu
                    orderKey={def.orderKey}
                    configKey={def.configKey}
                    label={def.label}
                    renderedOrderKeys={renderedOrderKeys}
                >
                    <span className={cn('block w-full', isLayoutNavCollapsed && 'flex justify-center')}>
                        <ButtonPrimitive
                            active={isActive}
                            className="group -outline-offset-2 w-full"
                            menuItem={!isLayoutNavCollapsed}
                            iconOnly={isLayoutNavCollapsed}
                            tooltip={tooltip}
                            tooltipPlacement="right"
                            onClick={() => def.identifier && handlePanelTriggerClick(def.identifier)}
                            data-attr={`menu-item-${def.identifier?.toLowerCase()}`}
                        >
                            <span
                                className={cn(
                                    'relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                    isActive && 'text-primary opacity-100'
                                )}
                            >
                                {def.icon}

                                <PanelIndicatorIcon />
                            </span>
                            {!isLayoutNavCollapsed && (
                                <>
                                    <span
                                        className={cn(
                                            'truncate text-secondary group-hover:text-primary',
                                            isActive && 'text-primary'
                                        )}
                                    >
                                        {def.label}
                                    </span>
                                    <span className="ml-auto pr-1">
                                        <IconChevronRight
                                            className={cn(
                                                'size-3 text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                                isActive && 'opacity-100'
                                            )}
                                        />
                                    </span>
                                </>
                            )}
                        </ButtonPrimitive>
                    </span>
                </NavItemContextMenu>
                {def.identifier === 'Products' && showToolsSearchRow && (
                    <ButtonPrimitive
                        menuItem
                        className="group -outline-offset-2"
                        data-attr="nav-tools-search-row"
                        onClick={() => {
                            posthog.capture('nav search clicked')
                            toggleCommand('nav-tools-row')
                        }}
                    >
                        <span className="relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                            <IconSearch />
                        </span>
                        <span className="truncate text-secondary group-hover:text-primary">Search</span>
                        <span className="ml-auto pr-1">
                            <RenderKeybind keybind={[keyBinds.search]} minimal />
                        </span>
                    </ButtonPrimitive>
                )}
            </Fragment>
        )
    }

    const projectItems = (
        <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
            {visibleDefs.map((def) => (def.kind === 'link' ? renderLinkDef(def) : renderTriggerDef(def)))}
            {hiddenDefs.length > 0 && !isLayoutNavCollapsed && (
                <MoreMenu hiddenDefs={hiddenDefs} onTriggerClick={handlePanelTriggerClick} />
            )}
        </div>
    )

    const recentsList =
        recentItemsLoading && recentItems.length === 0 ? (
            <div className="flex items-center justify-center py-2">
                <Spinner className="size-4" />
            </div>
        ) : recentItems.length === 0 ? (
            <span className="text-xs text-tertiary px-2 py-1">No recent items</span>
        ) : (
            <>
                {recentItems.map((item: FileSystemEntry) => {
                    const name = getItemName(item)
                    const isActive = item.href ? currentPath === item.href : false
                    return (
                        <Tooltip title={name} placement="right" key={item.id}>
                            <LinkListItem.Root>
                                <LinkListItem.Group>
                                    <Link
                                        to={item.href}
                                        buttonProps={{
                                            menuItem: true,
                                            active: isActive,
                                            className: 'group -outline-offset-2 pr-0',
                                        }}
                                        data-attr={`nav-recent-item-${item.id}`}
                                    >
                                        <LinkListItem.Content
                                            icon={iconForType(item.type as FileSystemIconType)}
                                            title={name}
                                            meta={
                                                <span title={humanFriendlyDetailedTime(item.last_viewed_at)}>
                                                    {formatRelativeDate(item.last_viewed_at)}
                                                </span>
                                            }
                                        />
                                    </Link>
                                    <LinkListItem.Trigger />
                                </LinkListItem.Group>
                                <LinkListItem.Actions>
                                    <PinToSidebarDropdownAction item={item} />
                                </LinkListItem.Actions>
                            </LinkListItem.Root>
                        </Tooltip>
                    )
                })}
            </>
        )

    const myToolsTree =
        uiCustomizationEnabled && enabledToolPaths.size === 0 ? (
            // Without this the section header opens onto nothing, reading as broken
            // rather than as "you haven't picked any tools yet".
            <span className="text-xs text-tertiary px-2 py-1 block">No tools shown</span>
        ) : (
            <ProjectTree
                root={!uiCustomizationEnabled && isEditMode ? 'products://' : 'custom-products://'}
                onlyTree
                treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                selectModeOverride={!uiCustomizationEnabled && isEditMode ? 'multi' : undefined}
                checkedItemsOverride={!uiCustomizationEnabled && isEditMode ? checkedTools : undefined}
                onItemCheckedOverride={
                    !uiCustomizationEnabled && isEditMode
                        ? (id) => {
                              // Tree item IDs for products:// are "products/{path}"
                              const toolPath = id.replace(/^products\//, '')
                              toggleTool(toolPath)
                          }
                        : undefined
                }
            />
        )

    if (flattened) {
        return (
            <ScrollableShadows
                className="flex-1"
                innerClassName="overflow-y-auto overflow-x-hidden px-2 focus-visible:outline-accent -outline-offset-2"
                direction="vertical"
                styledScrollbars
            >
                <div className="flex flex-col gap-px pt-1 group/colorful-product-icons colorful-product-icons-true">
                    {projectItems}
                    {showPinned && <NavPinned flattened />}
                    {isSidebarSectionShown('my_tools') && (
                        <div className="-ml-2 pl-3 pr-1 w-[calc(100%+(var(--spacing)*4))]">{myToolsTree}</div>
                    )}
                    {isSidebarSectionShown('recents') && recentsList}
                </div>
            </ScrollableShadows>
        )
    }

    return (
        <ScrollableShadows
            className="flex-1"
            innerClassName="overflow-y-auto overflow-x-hidden px-2 focus-visible:outline-accent -outline-offset-2"
            direction="vertical"
            styledScrollbars
        >
            <Collapsible
                open={expandedNavSections.project || isLayoutNavCollapsed ? true : false}
                onOpenChange={() => {
                    posthog.capture('nav section toggled', {
                        section: 'project',
                        is_open: !expandedNavSections.project,
                    })
                    toggleNavSection('project')
                }}
                data-attr="nav-section-project"
            >
                {!isLayoutNavCollapsed && (
                    <SectionTrigger icon={<IconFolder />} label="Project" isCollapsed={isLayoutNavCollapsed} />
                )}
                <Collapsible.Panel className={cn('pl-2 pt-1', isLayoutNavCollapsed && 'items-center pl-0')}>
                    {projectItems}
                </Collapsible.Panel>
            </Collapsible>

            {showPinned && <NavPinned flattened={false} />}

            {!isLayoutNavCollapsed && isSidebarSectionShown('recents') && (
                <Collapsible
                    open={expandedNavSections.recents ?? false}
                    onOpenChange={() => {
                        posthog.capture('nav section toggled', {
                            section: 'recents',
                            is_open: !expandedNavSections.recents,
                        })
                        toggleNavSection('recents')
                    }}
                    className="mt-2 group/colorful-product-icons colorful-product-icons-true"
                    data-attr="nav-section-recents"
                >
                    <SectionTrigger icon={<IconClock />} label="Recents" isCollapsed={isLayoutNavCollapsed} />
                    <Collapsible.Panel className="pl-2">{recentsList}</Collapsible.Panel>
                </Collapsible>
            )}

            {!isLayoutNavCollapsed && isSidebarSectionShown('my_tools') && (
                <Collapsible
                    open={expandedNavSections.tools ?? false}
                    onOpenChange={() => {
                        posthog.capture('nav section toggled', {
                            section: 'tools',
                            is_open: !expandedNavSections.tools,
                        })
                        toggleNavSection('tools')
                    }}
                    className="mt-2 group/colorful-product-icons colorful-product-icons-true"
                    data-attr="nav-section-tools"
                >
                    <div className="relative">
                        <SectionTrigger icon={<IconApps />} label="My Tools" isCollapsed={isLayoutNavCollapsed} />
                        {expandedNavSections.tools &&
                            (uiCustomizationEnabled ? (
                                <Link
                                    to={urls.settings('user-navigation')}
                                    tooltip="Choose which tools to show in the sidebar"
                                    tooltipPlacement="top"
                                    onClick={() => posthog.capture('nav tools customize clicked')}
                                    buttonProps={{
                                        iconOnly: true,
                                        size: 'xs',
                                        className:
                                            'absolute right-1 top-0 bottom-0 my-auto rounded-[var(--radius)] z-5',
                                    }}
                                    data-attr="nav-tools-customize-button"
                                >
                                    <IconGear className="size-3 text-secondary" />
                                </Link>
                            ) : (
                                <ButtonPrimitive
                                    iconOnly
                                    size="xs"
                                    tooltip={isEditMode ? 'Save' : 'Choose which tools to show in the sidebar'}
                                    tooltipPlacement="top"
                                    onClick={() => {
                                        if (isEditMode) {
                                            posthog.capture('nav tools edit saved')
                                            saveAndExitEditMode()
                                        } else {
                                            posthog.capture('nav tools edit toggled', { is_editing: true })
                                            enterEditMode()
                                        }
                                    }}
                                    data-attr="nav-tools-edit-button"
                                    className="absolute right-1 top-0 bottom-0 my-auto rounded-[var(--radius)] z-5"
                                >
                                    {isEditMode ? (
                                        <IconCheck className="size-3 text-primary" />
                                    ) : (
                                        <IconPencil className="size-3 text-secondary" />
                                    )}
                                </ButtonPrimitive>
                            ))}
                    </div>
                    <Collapsible.Panel className="-ml-2 pl-3 pr-1 w-[calc(100%+(var(--spacing)*4))]">
                        {!(expandedNavSections.tools ?? false) ? null : myToolsTree}
                    </Collapsible.Panel>
                </Collapsible>
            )}
        </ScrollableShadows>
    )
}
