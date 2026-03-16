import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { InAppNotification } from '~/types'

import { NotificationRow } from './NotificationRow'
import { notificationsMenuLogic } from './notificationsMenuLogic'

type NotificationTab = 'all' | 'unread'

export const NotificationsMenu = ({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element => {
    const { isNotificationsMenuOpen } = useValues(notificationsMenuLogic)
    const { setNotificationsMenuOpen } = useActions(notificationsMenuLogic)
    const { inAppNotifications, inAppUnreadCount, importantChangesLoading } = useValues(sidePanelNotificationsLogic)
    const { markAllAsRead } = useActions(sidePanelNotificationsLogic)

    const [activeTab, setActiveTab] = useState<NotificationTab>('all')

    const filteredNotifications =
        activeTab === 'unread' ? inAppNotifications.filter((n: InAppNotification) => !n.read) : inAppNotifications

    const handleCloseForNavigation = (): void => {
        setNotificationsMenuOpen(false)
    }

    return (
        <Menu.Root open={isNotificationsMenuOpen} onOpenChange={setNotificationsMenuOpen}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        tooltip={iconOnly ? 'Notifications' : undefined}
                        tooltipPlacement="right"
                        tooltipCloseDelayMs={0}
                        iconOnly={iconOnly}
                        className="group"
                        menuItem={!iconOnly}
                        data-attr="notifications-menu-button"
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconWithCount count={inAppUnreadCount}>
                                <IconNotification className="size-4.5" />
                            </IconWithCount>
                        </span>
                        {!iconOnly && <span className="-ml-[2px]">Notifications</span>}
                    </ButtonPrimitive>
                }
            />
            <Menu.Portal>
                <Menu.Backdrop className="fixed inset-0 z-[var(--z-modal)]" />
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="top"
                    align="start"
                    sideOffset={8}
                    collisionPadding={{ left: 0, top: 50, bottom: 50 }}
                >
                    <Menu.Popup className="primitive-menu-content w-[380px] max-h-[500px] flex flex-col">
                        <div className="flex items-center justify-between px-3 py-2 border-b border-primary shrink-0">
                            <div className="flex gap-1">
                                <button
                                    className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                                        activeTab === 'all'
                                            ? 'bg-fill-highlight-100 text-primary'
                                            : 'text-secondary hover:text-primary'
                                    }`}
                                    onClick={() => setActiveTab('all')}
                                >
                                    All
                                </button>
                                <button
                                    className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                                        activeTab === 'unread'
                                            ? 'bg-fill-highlight-100 text-primary'
                                            : 'text-secondary hover:text-primary'
                                    }`}
                                    onClick={() => setActiveTab('unread')}
                                >
                                    Unread
                                    {inAppUnreadCount > 0 && (
                                        <span className="ml-1 text-[10px] text-danger font-bold">
                                            {inAppUnreadCount}
                                        </span>
                                    )}
                                </button>
                            </div>
                            {inAppUnreadCount > 0 && (
                                <LemonButton size="xsmall" type="secondary" onClick={() => markAllAsRead()}>
                                    Mark all as read
                                </LemonButton>
                            )}
                        </div>
                        <ScrollableShadows
                            direction="vertical"
                            styledScrollbars
                            className="flex-1 overflow-hidden"
                            innerClassName="p-1"
                        >
                            {importantChangesLoading && inAppNotifications.length === 0 ? (
                                <div className="p-2">
                                    <LemonSkeleton className="h-10 my-1" repeat={5} fade />
                                </div>
                            ) : filteredNotifications.length > 0 ? (
                                <div className="flex flex-col gap-px">
                                    {filteredNotifications.map((notification: InAppNotification) => (
                                        <NotificationRow
                                            key={notification.id}
                                            notification={notification}
                                            onNavigate={handleCloseForNavigation}
                                        />
                                    ))}
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center p-6 text-center">
                                    <IconNotification className="size-8 text-muted mb-2" />
                                    <span className="text-sm text-secondary">
                                        {activeTab === 'unread' ? "You're all caught up!" : 'No notifications yet'}
                                    </span>
                                </div>
                            )}
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
