import { useActions, useValues } from 'kea'

import { IconArchive, IconArrowRight, IconNotification } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/lemon-ui/ScrollableShadows/ScrollableShadows'

import {
    NotificationGroup,
    sidePanelNotificationsLogic,
} from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PanelLayoutPanel } from '~/layout/panel-layout/PanelLayoutPanel'

import { NotificationGroupRow } from './NotificationGroupRow'
import { notificationsMenuLogic } from './notificationsMenuLogic'

export function NotificationsPanel(): JSX.Element {
    const { activeTab, isArchivedTab, visibleGroups, visibleGroupsLoading, showMarkAllRead, showLoadMore } =
        useValues(notificationsMenuLogic)
    const { setActiveTab } = useActions(notificationsMenuLogic)
    const { loadedUnreadCount, isLoadingMore, isLoadingMoreArchived, hasArchivableNotifications, archivingEnabled } =
        useValues(sidePanelNotificationsLogic)
    const { markAllAsRead, loadMoreNotifications, loadMoreArchived, archiveAll } =
        useActions(sidePanelNotificationsLogic)
    const { closePanel } = useActions(panelLayoutLogic)

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
                {isArchivedTab && (
                    <span className="px-2 py-1 text-xs font-medium rounded bg-fill-highlight-100 text-primary">
                        Archived
                    </span>
                )}
            </div>
            {showMarkAllRead && (
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

    const panelActions =
        !archivingEnabled || isArchivedTab
            ? undefined
            : [
                  {
                      'data-attr': 'notifications-view-archived',
                      onClick: () => setActiveTab('archived'),
                      children: (
                          <>
                              <IconArrowRight />
                              View archived
                          </>
                      ),
                  },
                  hasArchivableNotifications
                      ? {
                            'data-attr': 'notifications-archive-all',
                            onClick: () => archiveAll(),
                            children: (
                                <>
                                    <IconArchive />
                                    Archive all
                                </>
                            ),
                        }
                      : null,
              ]

    return (
        <PanelLayoutPanel panelName="notifications" searchField={header} panelActionsNewSceneLayout={panelActions}>
            <ScrollableShadows
                direction="vertical"
                styledScrollbars
                className="flex-1 overflow-hidden"
                innerClassName="p-1"
            >
                {visibleGroupsLoading ? (
                    <div className="p-2">
                        <LemonSkeleton className="h-10 my-1" repeat={5} fade />
                    </div>
                ) : visibleGroups.length > 0 ? (
                    <>
                        <div className="flex flex-col gap-px">
                            {visibleGroups.map((group: NotificationGroup) => (
                                <NotificationGroupRow
                                    key={group.group_key}
                                    group={group}
                                    onNavigate={() => closePanel()}
                                    readOnly={isArchivedTab}
                                />
                            ))}
                        </div>
                        {isArchivedTab && showLoadMore && (
                            <div className="p-2">
                                <LemonButton
                                    type="secondary"
                                    fullWidth
                                    center
                                    size="small"
                                    loading={isLoadingMoreArchived}
                                    onClick={() => loadMoreArchived()}
                                >
                                    Load more
                                </LemonButton>
                            </div>
                        )}
                        {!isArchivedTab && showLoadMore && (
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
                            {isArchivedTab
                                ? 'No archived notifications'
                                : activeTab === 'unread'
                                  ? "You're all caught up!"
                                  : 'No notifications yet'}
                        </span>
                    </div>
                )}
            </ScrollableShadows>
        </PanelLayoutPanel>
    )
}
