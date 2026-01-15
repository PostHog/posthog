import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useRef, useState } from 'react'

import {
    IconApps,
    IconChevronRight,
    IconDatabase,
    IconMessage,
    IconPlusSmall,
    IconSidebarClose,
    IconSidebarOpen,
} from '@posthog/icons'
import { LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { formatConversationDate } from 'scenes/max/utils'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'
import { ConversationStatus } from '~/types'

import { OrganizationMenu } from '../../lib/components/Account/OrganizationMenu'
import { ProjectMenu } from '../../lib/components/Account/ProjectMenu'
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

const MAX_RECENT_CONVERSATIONS = 5

function RecentConversations({ isCollapsed }: { isCollapsed: boolean }): JSX.Element {
    const { conversationHistory, conversationHistoryLoading } = useValues(maxGlobalLogic)
    const { searchParams } = useValues(router)
    const currentConversationId = searchParams?.chat
    const recentConversations = conversationHistory.slice(0, MAX_RECENT_CONVERSATIONS)

    if (conversationHistoryLoading && conversationHistory.length === 0) {
        return (
            <div className="flex flex-col gap-1 px-1">
                <LemonSkeleton className="h-7" />
                <LemonSkeleton className="h-7 opacity-60" />
                <LemonSkeleton className="h-7 opacity-30" />
            </div>
        )
    }

    if (recentConversations.length === 0) {
        return <div className="text-muted text-xs px-2 py-1">No chats yet</div>
    }

    return (
        <div className="flex flex-col gap-px">
            {recentConversations.map((conversation) => {
                const isActive = conversation.id === currentConversationId
                return (
                    <Link
                        key={conversation.id}
                        to={combineUrl(urls.ai(conversation.id), { from: 'history' }).url}
                        buttonProps={{
                            fullWidth: true,
                            active: isActive,
                        }}
                        tooltip={isCollapsed ? conversation.title : undefined}
                        tooltipPlacement="right"
                    >
                        <IconMessage className="size-4 text-secondary" />
                        {!isCollapsed && (
                            <span className="flex-1 line-clamp-1 text-primary text-sm">{conversation.title}</span>
                        )}
                        {conversation.status === ConversationStatus.InProgress && <Spinner className="h-3 w-3" />}
                        {!isCollapsed && (
                            <span className="opacity-30 text-xs">
                                {formatConversationDate(conversation.updated_at)}
                            </span>
                        )}
                    </Link>
                )
            })}
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
                        <ScrollableShadows
                            className={cn('flex-1', { 'rounded-tr': !isLayoutPanelVisible && !firstTabIsActive })}
                            innerClassName="overflow-y-auto overflow-x-hidden"
                            direction="vertical"
                            styledScrollbars
                        >
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

                                    <ButtonPrimitive
                                        iconOnly={isLayoutNavCollapsed}
                                        tooltip={isLayoutNavCollapsed ? 'Data' : undefined}
                                        tooltipPlacement="right"
                                        onClick={() => router.actions.push(urls.ai())}
                                        menuItem={!isLayoutNavCollapsed}
                                        className="hidden lg:flex"
                                    >
                                        <IconDatabase className="size-4 text-secondary" />
                                        Data
                                    </ButtonPrimitive>

                                    <ButtonPrimitive
                                        iconOnly={isLayoutNavCollapsed}
                                        tooltip={isLayoutNavCollapsed ? 'Data' : undefined}
                                        tooltipPlacement="right"
                                        onClick={() => router.actions.push(urls.ai())}
                                        menuItem={!isLayoutNavCollapsed}
                                        className="hidden lg:flex"
                                    >
                                        <IconApps className="size-4 text-secondary" />
                                        Apps
                                    </ButtonPrimitive>
                                </div>
                            </div>
                        </ScrollableShadows>

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
