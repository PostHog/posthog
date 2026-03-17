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

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { humanFriendlyDetailedTime } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

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
    const now = new Date()
    const date = new Date(dateStr)
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
                    onOpenChange={() => toggleNavSection('recents')}
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
                                const currentPath = removeProjectIdIfPresent(pathname)
                                const isActive = item.href ? currentPath === item.href : false
                                return (
                                    <Link
                                        key={item.id}
                                        to={item.href}
                                        buttonProps={{
                                            menuItem: true,
                                            active: isActive,
                                            className: 'group -outline-offset-2 pr-0',
                                        }}
                                        tooltip={name}
                                        tooltipPlacement="right"
                                        data-attr={`nav-recent-item-${item.id}`}
                                    >
                                        {iconForType(item.type as FileSystemIconType)}
                                        <span className="flex-1 line-clamp-1 text-secondary group-hover:text-primary">
                                            {name}
                                        </span>
                                        <span
                                            className="opacity-30 text-xs pr-1.5"
                                            title={humanFriendlyDetailedTime(item.last_viewed_at)}
                                        >
                                            {formatRelativeDate(item.last_viewed_at)}
                                        </span>
                                    </Link>
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
