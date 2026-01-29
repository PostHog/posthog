import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef, useState } from 'react'

import { IconChevronRight, IconPlusSmall, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AppsMenu } from '~/layout/panel-layout/ai-first/AppsMenu'
import { ConversationsMenu } from '~/layout/panel-layout/ai-first/ConversationsMenu'
import { RecentConversationsList } from '~/layout/panel-layout/ai-first/RecentConversationsList'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'

import { OrganizationMenu } from '../../lib/components/Account/OrganizationMenu'
import { ProjectMenu } from '../../lib/components/Account/ProjectMenu'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { DataMenu } from './ai-first/DataMenu'

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

export function AiFirstNavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)
    const { toggleLayoutNavCollapsed } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { user } = useValues(userLogic)
    const { firstTabIsActive } = useValues(sceneLogic)

    useAppShortcut({
        name: 'open-new-chat',
        keybind: [keyBinds.newChat],
        intent: 'Open new chat',
        interaction: 'function',
        callback: () => {
            newInternalTab(urls.ai())
        },
    })

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
                                    <LemonButton
                                        tooltip={
                                            <>
                                                <span>New chat</span> <RenderKeybind keybind={[keyBinds.newChat]} />
                                            </>
                                        }
                                        tooltipPlacement="right"
                                        onClick={() => router.actions.push(urls.ai())}
                                        type="secondary"
                                        className="[--lemon-button-padding-horizontal:0.5rem] [--lemon-button-gap:1rem]"
                                    >
                                        <IconPlusSmall className="size-4 text-secondary" />
                                        <span className="pl-[2px]">New chat</span>
                                    </LemonButton>

                                    <div className="flex flex-col gap-1">
                                        <Label intent="menu" className="text-xxs px-2 text-tertiary">
                                            Recent
                                        </Label>
                                        <div className="flex flex-col gap-px">
                                            <RecentConversationsList isCollapsed={isLayoutNavCollapsed} />
                                            <ConversationsMenu isCollapsed={isLayoutNavCollapsed} />
                                        </div>
                                    </div>

                                    <div className="flex flex-col gap-px w-full">
                                        {/* Data Menu */}
                                        <DataMenu />

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
