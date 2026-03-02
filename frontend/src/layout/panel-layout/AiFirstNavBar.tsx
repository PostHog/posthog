import { Collapsible } from '@base-ui/react/collapsible'
import { Menubar } from '@base-ui/react/menubar'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { useCallback, useRef } from 'react'

import {
    IconChevronRight,
    IconClock,
    IconFolder,
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
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { AiChatListItem } from 'scenes/max/components/List/AiChatListItem'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { AppsMenu } from '~/layout/panel-layout/ai-first/AppsMenu'
import { DataMenu } from '~/layout/panel-layout/ai-first/DataMenu'
import { FilesMenu } from '~/layout/panel-layout/ai-first/FilesMenu'
import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { RecentsMenu } from '~/layout/panel-layout/ai-first/RecentsMenu'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
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

function SectionChevron({ open }: { open: boolean }): JSX.Element {
    return (
        <IconChevronRight
            className={cn(
                'size-3 text-tertiary opacity-0 group-hover:opacity-100 transition-all duration-150',
                open && 'rotate-90'
            )}
        />
    )
}

function SectionTrigger({
    label,
    open,
    isCollapsed,
    icon,
}: {
    label: string
    open: boolean
    isCollapsed: boolean
    icon: React.ReactNode
}): JSX.Element {
    return (
        <Collapsible.Trigger
            className={cn('flex items-center w-full py-1 cursor-pointer group pl-2', isCollapsed && 'px-px')}
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
            {!isCollapsed && <SectionChevron open={open} />}
        </Collapsible.Trigger>
    )
}

function MenubarWithHoverCone({
    children,
    className,
    debug = false,
    ...menubarProps
}: React.ComponentProps<typeof Menubar> & { debug?: boolean }): JSX.Element {
    const coneRef = useRef<HTMLDivElement>(null)

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        const el = coneRef.current
        if (!el) {
            return
        }
        const rect = el.getBoundingClientRect()
        el.style.setProperty('--cone-x', `${e.clientX - rect.left}px`)
        el.style.setProperty('--cone-y', `${e.clientY - rect.top}px`)
    }, [])

    return (
        <div ref={coneRef} className="menubar-hover-cone relative" onMouseMove={handleMouseMove}>
            <Menubar className={className} {...menubarProps}>
                {children}
            </Menubar>
            <div className={cn('menubar-hover-cone-overlay', debug && 'debug')} />
        </div>
    )
}

export function AiFirstNavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { toggleLayoutNavCollapsed, toggleNavSection } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed, expandedNavSections } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { firstTabIsActive } = useValues(sceneLogic)
    const { toggleCommand } = useActions(commandLogic)
    const { conversationHistory, currentConversationId } = useValues(maxGlobalLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const recentChats = conversationHistory.slice(0, 3)

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
                        <Collapsible.Root
                            open={expandedNavSections.ai ?? true}
                            onOpenChange={() => toggleNavSection('ai')}
                            className={cn('px-1 mt-2', isLayoutNavCollapsed && 'mt-0')}
                        >
                            {!isLayoutNavCollapsed && (
                                <SectionTrigger
                                    icon={<IconSparkles />}
                                    label={isLayoutNavCollapsed ? 'AI' : 'PostHog AI'}
                                    open={expandedNavSections.ai ?? true}
                                    isCollapsed={isLayoutNavCollapsed}
                                />
                            )}
                            <Collapsible.Panel
                                className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}
                            >
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
                        </Collapsible.Root>

                        <Collapsible.Root
                            open={expandedNavSections.project ?? true}
                            onOpenChange={() => toggleNavSection('project')}
                            className="px-1 mt-2"
                        >
                            <SectionTrigger
                                icon={<IconFolder />}
                                label="Project"
                                open={expandedNavSections.project ?? true}
                                isCollapsed={isLayoutNavCollapsed}
                            />
                            <Collapsible.Panel
                                className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}
                            >
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

                                <MenubarWithHoverCone
                                    orientation="vertical"
                                    modal={false}
                                    className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}
                                >
                                    <AppsMenu isCollapsed={isLayoutNavCollapsed} />
                                    <DataMenu isCollapsed={isLayoutNavCollapsed} />
                                    <FilesMenu isCollapsed={isLayoutNavCollapsed} />
                                    <RecentsMenu isCollapsed={isLayoutNavCollapsed} />
                                </MenubarWithHoverCone>
                            </Collapsible.Panel>
                        </Collapsible.Root>

                        <Collapsible.Root
                            open={expandedNavSections.favorites ?? true}
                            onOpenChange={() => toggleNavSection('favorites')}
                            className="px-1 mt-2"
                        >
                            <SectionTrigger
                                icon={<IconStar />}
                                label="Starred"
                                open={expandedNavSections.favorites ?? true}
                                isCollapsed={isLayoutNavCollapsed}
                            />
                            <Collapsible.Panel
                                className={cn(
                                    '-ml-1 w-[calc(100%+(var(--spacing)*2))]',
                                    isLayoutNavCollapsed ? 'items-center' : ''
                                )}
                            >
                                <ProjectTree
                                    root="shortcuts://"
                                    onlyTree
                                    treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                                />
                            </Collapsible.Panel>
                        </Collapsible.Root>
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
        </div>
    )
}
