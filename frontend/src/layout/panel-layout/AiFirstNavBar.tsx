import { Collapsible } from '@base-ui/react/collapsible'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import {
    IconChevronRight,
    IconClock,
    IconHome,
    IconMessage,
    IconNotification,
    IconSidebarClose,
    IconSidebarOpen,
    IconSparkles,
} from '@posthog/icons'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AppsMenu } from '~/layout/panel-layout/ai-first/AppsMenu'
import { DataMenu } from '~/layout/panel-layout/ai-first/DataMenu'
import { RecentsMenu } from '~/layout/panel-layout/ai-first/RecentsMenu'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { ActivityTab } from '~/types'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'

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

export function AiFirstNavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { toggleLayoutNavCollapsed, toggleNavSection } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed, expandedNavSections } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { user } = useValues(userLogic)
    const { firstTabIsActive } = useValues(sceneLogic)

    return (
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
                <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                    <div className="flex-1 show-scrollbar-on-hover">
                        <div className="flex flex-col gap-px">
                            <div
                                className={cn('px-1 pt-2 flex flex-col gap-px', {
                                    'items-center': isLayoutNavCollapsed,
                                })}
                            >
                                <ButtonPrimitive
                                    menuItem={!isLayoutNavCollapsed}
                                    iconOnly={isLayoutNavCollapsed}
                                    tooltip={isLayoutNavCollapsed ? 'PostHog AI' : undefined}
                                    tooltipPlacement="right"
                                    onClick={() => router.actions.push(urls.ai())}
                                >
                                    <IconSparkles className="size-4 text-secondary" />
                                    {!isLayoutNavCollapsed && <span className="flex-1 text-left">PostHog AI</span>}
                                </ButtonPrimitive>

                                <ButtonPrimitive
                                    menuItem={!isLayoutNavCollapsed}
                                    iconOnly={isLayoutNavCollapsed}
                                    tooltip={isLayoutNavCollapsed ? 'Conversations' : undefined}
                                    tooltipPlacement="right"
                                    onClick={() => router.actions.push('#')}
                                >
                                    <IconMessage className="size-4 text-secondary" />
                                    {!isLayoutNavCollapsed && <span className="flex-1 text-left">Conversations</span>}
                                </ButtonPrimitive>

                                <AppsMenu isCollapsed={isLayoutNavCollapsed} />
                            </div>

                            {!isLayoutNavCollapsed && (
                                <Collapsible.Root
                                    open={expandedNavSections.project ?? true}
                                    onOpenChange={() => toggleNavSection('project')}
                                    className="px-1 mt-2"
                                >
                                    <Collapsible.Trigger className="flex items-center w-full px-2 py-1 cursor-pointer group">
                                        <Label intent="menu" className="text-xxs text-tertiary flex-1 text-left">
                                            Project
                                        </Label>
                                        <SectionChevron open={expandedNavSections.project ?? true} />
                                    </Collapsible.Trigger>
                                    <Collapsible.Panel className="flex flex-col gap-px">
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() => router.actions.push(urls.projectRoot())}
                                        >
                                            <IconHome className="size-4 text-secondary" />
                                            <span className="flex-1 text-left">Home</span>
                                        </ButtonPrimitive>

                                        <ButtonPrimitive menuItem onClick={() => router.actions.push(urls.inbox())}>
                                            <IconNotification className="size-4 text-secondary" />
                                            <span className="flex-1 text-left">Inbox</span>
                                        </ButtonPrimitive>

                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() =>
                                                router.actions.push(urls.activity(ActivityTab.ExploreEvents))
                                            }
                                        >
                                            <IconClock className="size-4 text-secondary" />
                                            <span className="flex-1 text-left">Activity</span>
                                        </ButtonPrimitive>

                                        <DataMenu />
                                        <RecentsMenu />
                                    </Collapsible.Panel>
                                </Collapsible.Root>
                            )}

                            {!isLayoutNavCollapsed && (
                                <Collapsible.Root
                                    open={expandedNavSections.files ?? true}
                                    onOpenChange={() => toggleNavSection('files')}
                                    className="px-1 mt-2"
                                >
                                    <Collapsible.Trigger className="flex items-center w-full px-2 py-1 cursor-pointer group">
                                        <Label intent="menu" className="text-xxs text-tertiary flex-1 text-left">
                                            Files
                                        </Label>
                                        <SectionChevron open={expandedNavSections.files ?? true} />
                                    </Collapsible.Trigger>
                                    <Collapsible.Panel>
                                        <ProjectTree root="project://" onlyTree />
                                    </Collapsible.Panel>
                                </Collapsible.Root>
                            )}

                            {!isLayoutNavCollapsed && (
                                <Collapsible.Root
                                    open={expandedNavSections.favorites ?? true}
                                    onOpenChange={() => toggleNavSection('favorites')}
                                    className="px-1 mt-2"
                                >
                                    <Collapsible.Trigger className="flex items-center w-full px-2 py-1 cursor-pointer group">
                                        <Label intent="menu" className="text-xxs text-tertiary flex-1 text-left">
                                            Favorites
                                        </Label>
                                        <SectionChevron open={expandedNavSections.favorites ?? true} />
                                    </Collapsible.Trigger>
                                    <Collapsible.Panel>
                                        <ProjectTree root="shortcuts://" onlyTree />
                                    </Collapsible.Panel>
                                </Collapsible.Root>
                            )}
                        </div>
                    </div>

                    <div className="border-b border-primary h-px" />

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
                                <IconSidebarClose className="text-tertiary" />
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
