import { useActions, useValues } from 'kea'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconHome,
    IconNotification,
    IconStar,
} from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { ContextMenuItem } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { joinPath, splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { BrowserLikeMenuItems } from '../../ProjectTree/menus/BrowserLikeMenuItems'
import { PanelIndicatorIcon, SectionTrigger } from '../Nav'
import { navRecentsLogic } from './navRecentsLogic'

const panelTriggerItems: {
    identifier: PanelLayoutNavIdentifier
    label: string
    icon: React.ReactNode
}[] = [
    {
        identifier: 'DataAndPeople',
        label: 'Data',
        icon: <IconDatabase />,
    },
    {
        identifier: 'Project',
        label: 'Files',
        icon: <IconFolderOpen className="stroke-[1.2]" />,
    },
    {
        identifier: 'Products',
        label: 'Apps',
        icon: <IconApps />,
    },
    {
        identifier: 'Shortcuts',
        label: 'Starred',
        icon: <IconStar />,
    },
]

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

function useStarredState(item: FileSystemEntry): {
    isAlreadyStarred: boolean
    addShortcutItem: (item: FileSystemEntry) => void
} {
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    const { shortcutNonFolderPaths } = useValues(projectTreeDataLogic)
    const shortcutPath = joinPath([splitPath(item.path).pop() ?? 'Unnamed'])
    return { isAlreadyStarred: shortcutNonFolderPaths.has(shortcutPath), addShortcutItem }
}

function AddToStarredContextAction({ item }: { item: FileSystemEntry }): JSX.Element {
    const { isAlreadyStarred, addShortcutItem } = useStarredState(item)

    if (isAlreadyStarred) {
        return (
            <ContextMenuItem asChild disabled>
                <ButtonPrimitive menuItem disabled>
                    <IconStar className="size-4 text-tertiary" />
                    Already starred
                </ButtonPrimitive>
            </ContextMenuItem>
        )
    }

    return (
        <ContextMenuItem asChild>
            <ButtonPrimitive menuItem onClick={() => addShortcutItem(item)}>
                <IconStar className="size-4 text-tertiary" />
                Add to starred
            </ButtonPrimitive>
        </ContextMenuItem>
    )
}

function AddToStarredDropdownAction({ item }: { item: FileSystemEntry }): JSX.Element {
    const { isAlreadyStarred, addShortcutItem } = useStarredState(item)

    if (isAlreadyStarred) {
        return (
            <DropdownMenuGroup>
                <BrowserLikeMenuItems MenuItem={DropdownMenuItem} href={item.href ?? ''} />
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild disabled>
                    <ButtonPrimitive menuItem disabled>
                        <IconStar className="size-4 text-tertiary" />
                        Already starred
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
                    <IconStar className="size-4 text-tertiary" />
                    Add to starred
                </ButtonPrimitive>
            </DropdownMenuItem>
        </DropdownMenuGroup>
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
    const { firstTabIsActive } = useValues(sceneLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const { recentItems, recentItemsLoading } = useValues(navRecentsLogic)
    const { loadRecentItems } = useActions(navRecentsLogic)
    const currentPath = removeProjectIdIfPresent(pathname)

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else if (activePanelIdentifier === item) {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    return (
        <ScrollableShadows
            className={cn('flex-1', {
                'rounded-tr': !isLayoutPanelVisible && !firstTabIsActive,
            })}
            innerClassName="overflow-y-auto overflow-x-hidden px-1"
            direction="vertical"
            styledScrollbars
        >
            <Collapsible
                open={expandedNavSections.project || isLayoutNavCollapsed ? true : false}
                onOpenChange={() => toggleNavSection('project')}
            >
                {!isLayoutNavCollapsed && (
                    <SectionTrigger icon={<IconFolder />} label="Project" isCollapsed={isLayoutNavCollapsed} />
                )}
                <Collapsible.Panel className={cn('pl-2', isLayoutNavCollapsed && 'items-center pl-0')}>
                    <NavLink
                        to={urls.projectRoot()}
                        label="Home"
                        icon={<IconHome />}
                        isCollapsed={isLayoutNavCollapsed}
                    />

                    {isProductAutonomyEnabled && (
                        <NavLink
                            to={urls.inbox()}
                            label="Inbox"
                            icon={<IconNotification />}
                            isCollapsed={isLayoutNavCollapsed}
                        />
                    )}

                    <NavLink
                        to={urls.activity(ActivityTab.ExploreEvents)}
                        label="Activity"
                        icon={<IconClock />}
                        isCollapsed={isLayoutNavCollapsed}
                    />

                    <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
                        {panelTriggerItems.map((item) => {
                            const isActive =
                                activePanelIdentifier === item.identifier ||
                                activePanelIdentifierFromUrlAiFirst === item.identifier
                            const tooltip = isLayoutNavCollapsed
                                ? isLayoutPanelVisible && activePanelIdentifier === item.identifier
                                    ? `Close ${item.label.toLowerCase()}`
                                    : `Open ${item.label.toLowerCase()}`
                                : undefined

                            return (
                                <ButtonPrimitive
                                    key={item.identifier}
                                    active={isActive}
                                    className="group -outline-offset-2"
                                    menuItem={!isLayoutNavCollapsed}
                                    iconOnly={isLayoutNavCollapsed}
                                    tooltip={tooltip}
                                    tooltipPlacement="right"
                                    onClick={() => handlePanelTriggerClick(item.identifier)}
                                    data-attr={`menu-item-${item.identifier.toLowerCase()}`}
                                >
                                    <span
                                        className={cn(
                                            'relative size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                            isActive && 'text-primary opacity-100'
                                        )}
                                    >
                                        {item.icon}

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
                                                {item.label}
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
                            )
                        })}
                    </div>
                </Collapsible.Panel>
            </Collapsible>

            {!isLayoutNavCollapsed && (
                <Collapsible
                    open={expandedNavSections.recents ?? false}
                    onOpenChange={() => {
                        if (!expandedNavSections.recents) {
                            loadRecentItems({})
                        }
                        toggleNavSection('recents')
                    }}
                    className="mt-2 group/colorful-product-icons colorful-product-icons-true"
                >
                    <SectionTrigger icon={<IconClock />} label="Recents" isCollapsed={isLayoutNavCollapsed} />
                    <Collapsible.Panel className="pl-2">
                        {recentItemsLoading && recentItems.length === 0 ? (
                            <div className="flex items-center justify-center py-2">
                                <Spinner className="size-4" />
                            </div>
                        ) : recentItems.length === 0 ? (
                            <span className="text-xs text-tertiary px-2 py-1">No recent items</span>
                        ) : (
                            recentItems.map((item: FileSystemEntry) => {
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
                                                    extraContextMenuItems={<AddToStarredContextAction item={item} />}
                                                >
                                                    <LinkListItem.Content
                                                        icon={iconForType(item.type as FileSystemIconType)}
                                                        title={name}
                                                        meta={
                                                            <span
                                                                title={humanFriendlyDetailedTime(item.last_viewed_at)}
                                                            >
                                                                {formatRelativeDate(item.last_viewed_at)}
                                                            </span>
                                                        }
                                                    />
                                                </Link>
                                                <LinkListItem.Trigger />
                                            </LinkListItem.Group>
                                            <LinkListItem.Actions>
                                                <AddToStarredDropdownAction item={item} />
                                            </LinkListItem.Actions>
                                        </LinkListItem.Root>
                                    </Tooltip>
                                )
                            })
                        )}
                    </Collapsible.Panel>
                </Collapsible>
            )}

            {!isLayoutNavCollapsed && (
                <Collapsible
                    open={expandedNavSections.apps ?? false}
                    onOpenChange={() => toggleNavSection('apps')}
                    className="mt-2 group/colorful-product-icons colorful-product-icons-true"
                >
                    <SectionTrigger icon={<IconApps />} label="Apps" isCollapsed={isLayoutNavCollapsed} />
                    <Collapsible.Panel className="-ml-2 pl-3 pr-1 w-[calc(100%+(var(--spacing)*4))]">
                        {(expandedNavSections.apps ?? false) && (
                            <ProjectTree
                                root="products://"
                                onlyTree
                                treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                            />
                        )}
                    </Collapsible.Panel>
                </Collapsible>
            )}
        </ScrollableShadows>
    )
}
