import { useActions, useValues } from 'kea'

import { IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'

import {
    NotificationGroup,
    sidePanelNotificationsLogic,
} from '~/layout/navigation/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PanelLayoutPanel } from '~/layout/panel-layout/PanelLayoutPanel'

import { NotificationGroupRow } from './NotificationGroupRow'
import { notificationsMenuLogic } from './notificationsMenuLogic'

export function NotificationsPanel(): JSX.Element {
    const { activeTab } = useValues(notificationsMenuLogic)
    const { setActiveTab } = useActions(notificationsMenuLogic)
    const {
        groups,
        loadedUnreadCount,
        inAppUnreadCount,
        importantChangesLoading,
        hasMoreNotifications,
        isLoadingMore,
    } = useValues(sidePanelNotificationsLogic)
    const { markAllAsRead, loadMoreNotifications } = useActions(sidePanelNotificationsLogic)
    const { closePanel } = useActions(panelLayoutLogic)

    const filteredGroups = activeTab === 'unread' ? groups.filter((g: NotificationGroup) => g.has_unread) : groups

    const header = (
        <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className="flex gap-1 pl-1">
                {/* TODO: make tab primitives */}
                <button
                    className={`px-2 py-1 text-xs font-medium rounded transition-colors ${
                        activeTab === 'all' ? 'bg-fill-highlight-100 text-primary' : 'text-secondary hover:text-primary'
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
                    {loadedUnreadCount > 0 && (
                        <span className="ml-1 text-[10px] text-danger font-bold">{loadedUnreadCount}</span>
                    )}
                </button>
            </div>
            {/* Only surface "Mark all read" when unread items sit on not-yet-loaded pages — the ones
                already loaded get cleared by the 3s auto-mark-on-view as the user scrolls. */}
            {hasMoreNotifications && inAppUnreadCount > loadedUnreadCount && (
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => markAllAsRead()}
                    className="ml-auto"
                    data-attr="notifications-mark-all-read"
                >
                    Mark all read
                </LemonButton>
            )}
        </div>
    )

    return (
        <PanelLayoutPanel searchField={header}>
            <ScrollableShadows
                direction="vertical"
                styledScrollbars
                className="flex-1 overflow-hidden"
                innerClassName="p-1"
            >
                {importantChangesLoading && groups.length === 0 ? (
                    <div className="p-2">
                        <LemonSkeleton className="h-10 my-1" repeat={5} fade />
                    </div>
                ) : filteredGroups.length > 0 ? (
                    <>
                        <div className="flex flex-col gap-1">
                            {filteredGroups.map((group: NotificationGroup) => (
                                <NotificationGroupRow
                                    key={group.group_key}
                                    group={group}
                                    onNavigate={() => closePanel()}
                                />
                            ))}
                        </div>
                        {hasMoreNotifications && activeTab === 'all' && (
                            <div className="p-2">
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    size="small"
                                    loading={isLoadingMore}
                                    onClick={() => loadMoreNotifications()}
                                >
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                    </>
                ) : (
                    <div className="flex flex-col items-center justify-center p-6 text-center">
                        <IconNotification className="size-8 text-muted mb-2" />
                        <span className="text-sm text-secondary">
                            {activeTab === 'unread' ? "You're all caught up!" : 'No notifications yet'}
                        </span>
                    </div>
                )}
            </ScrollableShadows>
        </PanelLayoutPanel>
    )
}
