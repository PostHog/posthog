import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolder,
    IconFolderOpen,
    IconHome,
    IconNotification,
    IconSearch,
    IconSparkles,
    IconStar,
} from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { AiChatListItem } from 'scenes/max/components/List/AiChatListItem'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { maxGlobalLogic } from '~/scenes/max/maxGlobalLogic'
import { ActivityTab } from '~/types'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { NavBarFooter } from './NavBarFooter'

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

function SectionTrigger({
    label,
    isCollapsed,
    icon,
}: {
    label: string
    isCollapsed: boolean
    icon: React.ReactNode
}): JSX.Element {
    return (
        <Collapsible.Trigger
            className={cn(
                'flex items-center py-1 cursor-pointer group pl-2 sticky top-0 bg-surface-tertiary z-10 -mx-1 px-2 w-[calc(100%+(var(--spacing)*2))]',
                isCollapsed && 'mx-0 w-full px-px'
            )}
        >
            <Label
                intent="menu"
                className={cn(
                    'text-xxs text-tertiary text-left group-hover:text-primary mr-1',
                    isCollapsed && 'text-[7px] m-0 w-full text-center'
                )}
            >
                {icon && !isCollapsed && <span className="size-3 mr-1">{icon}</span>}
                {label}
            </Label>
        </Collapsible.Trigger>
    )
}

export function AiFirstNavBar({ children }: { children?: React.ReactNode }): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        toggleNavSection,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        isLayoutNavCollapsed,
        expandedNavSections,
        activePanelIdentifier,
        activePanelIdentifierFromUrlAiFirst,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { firstTabIsActive } = useValues(sceneLogic)
    const { toggleCommand } = useActions(commandLogic)
    const { conversationHistory, currentConversationId } = useValues(maxGlobalLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const recentChats = conversationHistory.slice(0, 3)

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else if (activePanelIdentifier === item) {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

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

    return (
        <div className="flex gap-0 relative">
            <nav
                className={cn(
                    navBarStyles({
                        isLayoutNavCollapsed,
                        isMobileLayout,
                    }),
                    isLayoutNavCollapsed && 'gap-px'
                )}
                ref={containerRef}
            >
                <div
                    className={cn(
                        'flex justify-between items-center',
                        isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'
                    )}
                >
                    <div
                        className={cn('flex gap-1 rounded-md w-full px-1', {
                            'flex-col items-center pt-2': isLayoutNavCollapsed,
                        })}
                    >
                        <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />

                        <ButtonPrimitive
                            iconOnly
                            tooltip={
                                <>
                                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                                </>
                            }
                            onClick={() => toggleCommand()}
                        >
                            <IconSearch className="size-4 text-secondary" />
                        </ButtonPrimitive>
                    </div>
                </div>

                <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                    <ScrollableShadows
                        className={cn('flex-1', { 'rounded-tr': !isLayoutPanelVisible && !firstTabIsActive })}
                        innerClassName="overflow-y-auto overflow-x-hidden"
                        direction="vertical"
                        styledScrollbars
                    >
                        <Collapsible
                            open={expandedNavSections.ai ?? true}
                            onOpenChange={() => toggleNavSection('ai')}
                            className={cn('px-1', isLayoutNavCollapsed && 'mt-0')}
                        >
                            {!isLayoutNavCollapsed && (
                                <Collapsible.Trigger icon={<IconSparkles />}>PostHog AI</Collapsible.Trigger>
                            )}
                            <Collapsible.Panel className={cn(isLayoutNavCollapsed && 'items-center')}>
                                <NavLink
                                    to={urls.ai()}
                                    label="New chat"
                                    icon={
                                        <span className="text-ai">
                                            <svg
                                                width="24"
                                                height="24"
                                                viewBox="0 0 24 24"
                                                fill="none"
                                                stroke="currentColor"
                                                strokeWidth="2"
                                                strokeLinecap="round"
                                            >
                                                <line x1="12" y1="5" x2="12" y2="19" />
                                                <line x1="5" y1="12" x2="19" y2="12" />
                                            </svg>
                                        </span>
                                    }
                                    isCollapsed={isLayoutNavCollapsed}
                                />
                                {!isLayoutNavCollapsed &&
                                    recentChats.map((conversation) => (
                                        <AiChatListItem
                                            key={conversation.id}
                                            conversationId={conversation.id}
                                            title={conversation.title}
                                            status={conversation.status}
                                            updatedAt={conversation.updated_at}
                                            isActive={conversation.id === currentConversationId}
                                        />
                                    ))}
                            </Collapsible.Panel>
                        </Collapsible>

                        <Collapsible
                            open={expandedNavSections.project ?? true}
                            onOpenChange={() => toggleNavSection('project')}
                            className="px-1 mt-1"
                        >
                            <Collapsible.Trigger
                                icon={!isLayoutNavCollapsed ? <IconFolder /> : undefined}
                                className={cn(isLayoutNavCollapsed && 'px-px')}
                                labelClassName={cn(isLayoutNavCollapsed && 'text-[7px] m-0 w-full text-center')}
                                hideChevron={isLayoutNavCollapsed}
                            >
                                Project
                            </Collapsible.Trigger>
                            <Collapsible.Panel className={cn(isLayoutNavCollapsed && 'items-center')}>
                                <NavLink
                                    to={urls.projectHomepage()}
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
                                                className="group"
                                                menuItem={!isLayoutNavCollapsed}
                                                iconOnly={isLayoutNavCollapsed}
                                                tooltip={tooltip}
                                                tooltipPlacement="right"
                                                onClick={() => handlePanelTriggerClick(item.identifier)}
                                                data-attr={`menu-item-${item.identifier.toLowerCase()}`}
                                            >
                                                <span className="size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50">
                                                    {item.icon}
                                                </span>
                                                {!isLayoutNavCollapsed && (
                                                    <>
                                                        <span className="truncate">{item.label}</span>
                                                        <span className="ml-auto pr-1">
                                                            <IconChevronRight
                                                                className={cn(
                                                                    'size-3 text-tertiary opacity-50 group-hover:opacity-100 transition-all duration-50',
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

                        <Collapsible
                            open={expandedNavSections.apps ?? false}
                            onOpenChange={() => toggleNavSection('apps')}
                            className="px-2 mt-1 group/colorful-product-icons colorful-product-icons-true"
                        >
                            <SectionTrigger
                                icon={<IconApps />}
                                label={isLayoutNavCollapsed ? 'Apps' : 'All apps'}
                                isCollapsed={isLayoutNavCollapsed}
                            />
                            <Collapsible.Panel
                                className={cn(
                                    '-ml-2 w-[calc(100%+(var(--spacing)*4))]',
                                    isLayoutNavCollapsed ? 'items-center' : ''
                                )}
                            >
                                <ProjectTree
                                    root="products://"
                                    onlyTree
                                    treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                                />
                            </Collapsible.Panel>
                        </Collapsible>
                    </ScrollableShadows>

                    <div className="border-b border-primary h-px" />

                    <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
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
                        className={cn('top-[calc(var(--scene-layout-header-height)+7px)] right-[-1px] bottom-4', {
                            'top-[var(--scene-layout-header-height)]': firstTabIsActive,
                            'top-0': isLayoutPanelVisible,
                        })}
                        offset={0}
                    />
                )}
            </nav>

            {children}
        </div>
    )
}
